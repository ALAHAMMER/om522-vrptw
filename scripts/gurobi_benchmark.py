"""Labeled benchmark (NOT a graded method): an exact VRPTW MIP solved by Gurobi.

The project guide allows a general solver on a model the team formulates; this benchmark exists to
measure how far the LNS is from optimal. It needs a Gurobi license, so it runs in the separate
`benchmark` Pixi environment and is never used by `pixi run solve`.

Usage: pixi run -e benchmark gurobi-benchmark [instance ...] [--time-limit SECONDS]

Formulation (two-index, homogeneous fleet; Desrochers, Desrosiers & Solomon 1992 style):
    x[i,j] in {0,1}  vehicle drives i -> j            (0 = depot)
    t[i]   in [ws_i, we_i]  service start at customer i
    u[i]   in [q_i, Q]      load delivered up to and including i
    min  sum T_ij x_ij
    s.t. each customer has one incoming and one outgoing arc
         sum_j x_0j <= number of vehicles
         t_j >= t_i + s_i + T_ij - M_ij (1 - x_ij)          (time propagation; waiting allowed)
         t_j >= S + T_0j               if x_0j = 1           (leave depot at shift start)
         t_i + s_i + T_i0 <= E         if x_i0 = 1           (return by shift end)
         u_j >= u_i + q_j - Q (1 - x_ij)                     (capacity, also removes subtours)
The time constraints also eliminate subtours because service times are positive.
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path

import gurobipy as gp
import polars as pl
from gurobipy import GRB

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vrptw.checker import check_decision  # noqa: E402
from vrptw.decision import build_decision, measures, write_outputs  # noqa: E402
from vrptw.instance import Instance, load_instance  # noqa: E402
from vrptw.lns import solve_lns  # noqa: E402

DATA = ROOT / "data" / "option_03"
OUT = ROOT / "results"
DEFAULT_INSTANCES = ["hand_checkable", "development_small", "development_medium", "development_large"]
STATUS = {GRB.OPTIMAL: "optimal", GRB.TIME_LIMIT: "time limit", GRB.INFEASIBLE: "infeasible"}


def earliest_service_starts(inst: Instance, shift_start: float) -> list[float]:
    """Earliest feasible service start at every customer over any path from the depot
    (label-correcting shortest path with waiting; inf = unreachable within its window)."""
    n, T = inst.n, inst.T
    earliest = [shift_start] + [math.inf] * n
    for i in range(1, n + 1):
        arrival = shift_start + T[0][i]
        if arrival <= inst.we[i] + 1e-8:
            earliest[i] = max(arrival, inst.ws[i])
    changed = True
    while changed:
        changed = False
        for i in range(1, n + 1):
            if not math.isfinite(earliest[i]):
                continue
            leave = earliest[i] + inst.service[i]
            for j in range(1, n + 1):
                arrival = leave + T[i][j]
                if j != i and arrival <= inst.we[j] + 1e-8 and max(arrival, inst.ws[j]) < earliest[j] - 1e-12:
                    earliest[j] = max(arrival, inst.ws[j])
                    changed = True
    return earliest


def build_model(inst: Instance, time_limit: float, warm_start: list[list[int]] | None):
    if len(set(inst.cap)) > 1 or len(set(inst.shift_start)) > 1 or len(set(inst.shift_end)) > 1:
        raise ValueError("this two-index benchmark model assumes identical vehicles")
    n, T = inst.n, inst.T
    Q, S, E = inst.cap[0], inst.shift_start[0], inst.shift_end[0]
    nodes = range(n + 1)
    customers = range(1, n + 1)

    # Arc pre-processing: drop arcs that can never be used feasibly. The earliest possible service
    # start at each customer is taken over ANY path from the depot, not just the direct leg: when
    # travel times break the triangle inequality, going via another customer can arrive sooner.
    earliest = earliest_service_starts(inst, S)
    arcs = []
    for i in nodes:
        for j in nodes:
            if i == j or (i == 0 and j == 0):
                continue
            if i and j and inst.demand[i] + inst.demand[j] > Q:
                continue
            if i and not math.isfinite(earliest[i]):
                continue  # customer i cannot be reached in time at all
            earliest_i = earliest[i] if i else S
            if j and earliest_i + inst.service[i] + T[i][j] > inst.we[j]:
                continue
            arcs.append((i, j))

    m = gp.Model("vrptw")
    m.Params.OutputFlag = 0
    m.Params.TimeLimit = time_limit
    m.Params.Seed = 522
    m.Params.Threads = 0
    x = m.addVars(arcs, vtype=GRB.BINARY, name="x")
    t = m.addVars(customers, lb={i: inst.ws[i] for i in customers}, ub={i: inst.we[i] for i in customers}, name="t")
    u = m.addVars(customers, lb={i: inst.demand[i] for i in customers}, ub=Q, name="u")
    m.setObjective(gp.quicksum(T[i][j] * x[i, j] for i, j in arcs), GRB.MINIMIZE)

    m.addConstrs((x.sum(i, "*") == 1 for i in customers), name="out")
    m.addConstrs((x.sum("*", j) == 1 for j in customers), name="in")
    m.addConstr(x.sum(0, "*") <= len(inst.vehicle_ids), name="fleet")
    for i, j in arcs:
        if i and j:
            big_m = inst.we[i] + inst.service[i] + T[i][j] - inst.ws[j]
            if big_m > 0:
                m.addConstr(t[j] >= t[i] + inst.service[i] + T[i][j] - big_m * (1 - x[i, j]))
            m.addConstr(u[j] >= u[i] + inst.demand[j] - Q * (1 - x[i, j]))
        elif i == 0:
            m.addConstr(t[j] >= S + T[0][j] - (S + T[0][j] - inst.ws[j]) * (1 - x[0, j]))
        else:  # j == 0, return to depot
            m.addConstr(t[i] + inst.service[i] + T[i][0] <= E + (inst.we[i] + inst.service[i] + T[i][0] - E)
                        * (1 - x[i, 0]))

    if warm_start:  # MIP start from the LNS plan
        used = {(a, b) for r in warm_start if r for a, b in zip([0, *r], [*r, 0])}
        for arc in arcs:
            x[arc].Start = 1.0 if arc in used else 0.0
    return m, x, arcs


def extract_routes(inst: Instance, x, arcs) -> list[list[int]]:
    succ = {}
    starts = []
    for i, j in arcs:
        if x[i, j].X > 0.5:
            if i == 0:
                starts.append(j)
            else:
                succ[i] = j
    routes = []
    for first in sorted(starts):
        route, c = [], first
        while c != 0:
            route.append(c)
            c = succ[c]
        routes.append(route)
    plan = [[] for _ in inst.vehicle_ids]
    for v, route in enumerate(routes):
        plan[v] = route
    return plan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("instances", nargs="*", default=DEFAULT_INSTANCES)
    parser.add_argument("--time-limit", type=float, default=300.0, help="Gurobi seconds per instance")
    args = parser.parse_args()

    rows = []
    for name in args.instances:
        inst = load_instance(DATA / name)
        started = time.perf_counter()
        lns = solve_lns(inst)
        lns_seconds = time.perf_counter() - started
        lns_travel = measures(inst, lns.routes)["total_travel_time"]

        model, x, arcs = build_model(inst, args.time_limit, lns.routes)
        started = time.perf_counter()
        model.optimize()
        seconds = time.perf_counter() - started
        status = STATUS.get(model.Status, str(model.Status))
        row = {"instance": name, "customers": inst.n, "arcs": len(arcs), "lns_travel": lns_travel,
               "lns_seconds": lns_seconds, "time_limit_s": args.time_limit, "gurobi_status": status, "gurobi_seconds": seconds}
        if model.SolCount:
            plan = extract_routes(inst, x, arcs)
            decision = build_decision(inst, plan)
            check = check_decision(DATA / name, decision)
            if check["feasible"]:  # a plan that fails the independent checker is never saved
                write_outputs(OUT / "decisions" / name / "gurobi_benchmark", decision,
                              {"method": "Gurobi MIP benchmark (not a graded method)", "status": status,
                               **measures(inst, plan), "seconds": seconds, "best_bound": model.ObjBound,
                               "mip_gap": model.MIPGap})
            else:
                print(f"WARNING {name}: Gurobi plan failed the checker: {check['violations'][:3]}", flush=True)
            bound = model.ObjBound
            row |= {"gurobi_travel": check["total_travel_time"], "gurobi_feasible": check["feasible"],
                    "gurobi_vehicles": check["vehicles_used"], "lower_bound": bound,
                    "gurobi_gap_pct": 100 * model.MIPGap,
                    # Two readings of the same bound (they differ only in the denominator):
                    # the most of the LNS cost an optimal plan could save, (LNS - bound) / LNS ...
                    "lns_max_saving_pct": 100 * (lns_travel - bound) / lns_travel,
                    # ... and the most the LNS cost can exceed the optimum, (LNS - bound) / bound.
                    "lns_max_above_optimal_pct": 100 * (lns_travel - bound) / bound if bound > 0 else math.inf}
        rows.append(row)
        print(json.dumps(row, default=float), flush=True)

    table = pl.DataFrame(rows)
    table = table.select("instance", "customers", "arcs", "lns_travel", "lns_seconds", "time_limit_s",
                         *[c for c in table.columns if c not in {"instance", "customers", "arcs", "lns_travel",
                                                                  "lns_seconds", "time_limit_s"}])
    csv_path = OUT / "gurobi_benchmark.csv"
    if csv_path.exists():  # keep rows for instances not rerun this time
        previous = pl.read_csv(csv_path).filter(~pl.col("instance").is_in(table["instance"].to_list()))
        table = pl.concat([previous, table], how="diagonal_relaxed")
    order = {name: k for k, name in enumerate(DEFAULT_INSTANCES)}
    table = table.sort(pl.col("instance").replace_strict(order, default=99))
    table.write_csv(csv_path)
    lines = ["# Gurobi MIP benchmark (labeled benchmark, not a graded method)", "",
             "Two-index VRPTW MIP, warm-started with the LNS plan (MIP start), Gurobi seed 522; `time_limit_s` is each row's limit. "
             "Arcs are pruned only when no path from the depot can reach them in time. "
             "`lns_max_saving_pct` = (LNS - lower bound) / LNS: the most of the LNS travel an optimal plan "
             "could save. `lns_max_above_optimal_pct` = (LNS - lower bound) / lower bound: the most the LNS "
             "travel can exceed the optimum. Both are 0 when the LNS plan is proven optimal.", "",
             "| " + " | ".join(table.columns) + " |", "|" + "---|" * table.width]
    for r in table.iter_rows():
        lines.append("| " + " | ".join(f"{v:,.3f}" if isinstance(v, float) else str(v) for v in r) + " |")
    (OUT / "GUROBI_BENCHMARK.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
