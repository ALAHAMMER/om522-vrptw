"""Regenerate every submitted comparison table, stress-test result, and plot.

Usage: pixi run compare            (writes everything under results/)

Steps
1. Generate and save the stress-test scenarios for development_medium FIRST, before any method runs.
2. Run both methods with default settings on hand_checkable and the three development instances and
   verify every decision with the independent checker. If any method returns nothing or a plan that
   fails the checker, the script stops BEFORE writing any decision, table, or plot.
3. Execute both fixed plans for development_medium under the saved scenarios (base setting), plus a
   harsher sensitivity setting used to state when the recommendation would change, and find the
   uniform slowdown at which each plan first misses a window.
4. Run both methods on five 60-customer proxy instances (random subsets of development_large, the
   held-out size), saved under results/proxies/.
5. Draw route maps that mark every crossing and test whether each same-route crossing can be removed.
6. Write tables (CSV + Markdown) and plots.
7. Build the management scenarios (scripts/scenarios.py), which reuse the saved stress scenarios.
"""

import dataclasses
import json
import platform
import random
import shutil
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vrptw.checker import check_decision  # noqa: E402
from vrptw.crossings import find_crossings, plot_routes_with_crossings  # noqa: E402
from vrptw.decision import build_decision, measures, write_outputs  # noqa: E402
from vrptw.instance import load_instance  # noqa: E402
from vrptw.lns import (  # noqa: E402
    DEFAULT_ITERATIONS, DEFAULT_RESTARTS, DEFAULT_SEED, DEFAULT_TIME_CAP, solve_lns,
)
from vrptw.rule import nearest_feasible_neighbor  # noqa: E402
from vrptw.stress import (  # noqa: E402
    ARC_CV, DAY_CV, N_SCENARIOS, SCENARIO_SEED, execute_plan, generate_scenarios, run_stress_test,
    summarize_stress,
)

DATA = ROOT / "data" / "option_03"
OUT = ROOT / "results"
INSTANCES = ["hand_checkable", "development_small", "development_medium", "development_large"]
STRESS_INSTANCE = "development_medium"
SETTINGS = {  # name -> (mean day factor, day CV)
    "base": (1.0, DAY_CV),
    "heavy_congestion": (1.15, 0.3),
}
COLORS = {"rule": "#d95f02", "lns": "#1b9e77", "lns_buffer15": "#7570b3"}
BUFFER = 1.15  # sensitivity plan: LNS planned with every travel time inflated by 15%
PROXY_SEEDS = range(5)       # 60-customer proxies: random.Random(k).sample of development_large
PROXY_SIZE, PROXY_VEHICLES = 60, 24


def make_proxy(k: int, folder: Path) -> Path:
    """Write a 60-customer instance drawn from development_large (same fleet type, first 24 vehicles)."""
    source = DATA / "development_large"
    customers = pl.read_csv(source / "customers.csv", infer_schema=False)
    chosen = sorted(random.Random(k).sample(customers.get_column("customer_id").to_list(), PROXY_SIZE))
    keep = set(chosen) | {"DEPOT"}
    folder.mkdir(parents=True, exist_ok=True)
    customers.filter(pl.col("customer_id").is_in(chosen)).write_csv(folder / "customers.csv")
    (pl.read_csv(source / "travel_times.csv", infer_schema=False)
     .filter(pl.col("from_id").is_in(keep) & pl.col("to_id").is_in(keep))
     .write_csv(folder / "travel_times.csv"))
    pl.read_csv(source / "vehicles.csv", infer_schema=False).head(PROXY_VEHICLES).write_csv(folder / "vehicles.csv")
    shutil.copy(source / "depots.csv", folder / "depots.csv")
    return folder


def first_violation_factor(inst, routes) -> float:
    """Smallest uniform slowdown (all travel times x f, f in steps of 0.01) that breaks the fixed plan."""
    for f in np.arange(1.0, 3.0001, 0.01):
        if execute_plan(inst, routes, np.full(inst.T_np.shape, f))["violations"]:
            return round(float(f), 2)
    return float("inf")


def markdown_table(frame: pl.DataFrame, digits: int = 3) -> str:
    def fmt(value):
        return f"{value:,.{digits}f}" if isinstance(value, float) else str(value)
    lines = ["| " + " | ".join(frame.columns) + " |", "|" + "---|" * frame.width]
    lines += ["| " + " | ".join(fmt(v) for v in row) + " |" for row in frame.iter_rows()]
    return "\n".join(lines)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    pl.Config.set_tbl_formatting("ASCII_MARKDOWN")

    # 1. Scenarios first, so both plans face identical, pre-committed realizations.
    medium = load_instance(DATA / STRESS_INSTANCE)
    scenario_files = {}
    for name, (day_mean, day_cv) in SETTINGS.items():
        scenario_files[name] = generate_scenarios(
            medium, OUT / "stress" / f"scenarios_{name}.parquet", day_mean=day_mean, day_cv=day_cv)
    print(f"Saved {N_SCENARIOS} scenarios per setting (seed {SCENARIO_SEED}) to results/stress/")

    # 2. Deterministic comparison. Everything is solved and checked first; nothing is written until
    #    every plan has passed the independent checker.
    rows, plans, histories, pending, failures = [], {}, {}, [], []
    instances = {name: load_instance(DATA / name) for name in INSTANCES}
    for name in INSTANCES:
        inst = instances[name]
        for method in ("rule", "lns"):
            started = time.perf_counter()
            if method == "rule":
                routes, extra = nearest_feasible_neighbor(inst), {"stop_reason": "every customer served"}
            else:
                result = solve_lns(inst)
                routes = result.routes
                histories[name] = result.history
                # Same run-status fields as the summary written by `pixi run solve`.
                extra = {"seed": DEFAULT_SEED, "restarts": DEFAULT_RESTARTS,
                         "iterations_per_run": DEFAULT_ITERATIONS, "iterations_run_total": result.iterations_run,
                         "time_cap_seconds": DEFAULT_TIME_CAP, "stop_reason": result.stop_reason,
                         "start": result.start_method}
            seconds = time.perf_counter() - started
            if routes is None:
                failures.append(f"{name} / {method}: no feasible decision found")
                continue
            decision = build_decision(inst, routes)
            checked = check_decision(DATA / name, decision)
            if not checked["feasible"]:
                failures.append(f"{name} / {method}: checker violations {checked['violations'][:3]}")
            pending.append((OUT / "decisions" / name / method, decision,
                            {"status": "feasible decision found", "method": method, **extra,
                             **measures(inst, routes), "computation_seconds": seconds}))
            rows.append({
                "instance": name, "customers": inst.n, "method": method,
                "feasible": checked["feasible"],
                "total_travel_time": checked["total_travel_time"],
                "vehicles_used": checked["vehicles_used"],
                "waiting_time": checked["waiting_time"],
                "seconds": seconds,
            })
            plans[(name, method)] = routes
            print(f"{name:20s} {method:4s} feasible={checked['feasible']} "
                  f"travel={checked['total_travel_time']:.3f} vehicles={checked['vehicles_used']} {seconds:.1f}s")
    if failures:
        raise SystemExit("Stopping before writing any results:\n  " + "\n  ".join(failures))
    for folder, decision, summary in pending:
        write_outputs(folder, decision, summary)
    comparison = pl.DataFrame(rows)
    comparison.write_csv(OUT / "comparison.csv")

    wide = (
        comparison.pivot(on="method", index=["instance", "customers"],
                         values=["total_travel_time", "vehicles_used", "seconds"])
        .with_columns(
            (100 * (1 - pl.col("total_travel_time_lns") / pl.col("total_travel_time_rule")))
            .alias("travel_saved_pct"))
    )
    wide.write_csv(OUT / "comparison_wide.csv")

    # Edge case: both methods must report that no feasible decision exists.
    edge = load_instance(DATA / "edge_case")
    edge_rows = pl.DataFrame([
        {"method": "rule", "result": "no feasible decision found" if nearest_feasible_neighbor(edge) is None else "plan"},
        {"method": "lns", "result": "no feasible decision found" if solve_lns(edge).routes is None else "plan"},
    ])

    # 3. Stress test of the fixed medium plans.
    stress_tables = {}
    medium_plans = {m: plans[(STRESS_INSTANCE, m)] for m in ("rule", "lns")}
    # Sensitivity plan (not a third method): the same LNS planned on travel times x BUFFER, so every
    # route keeps slack for congestion. Earlier arrivals never make a later stop late, so the plan is
    # also feasible on the true travel times; its nominal travel shows what the buffer costs.
    buffered_inst = dataclasses.replace(medium, T=(medium.T_np * BUFFER).tolist(), T_np=medium.T_np * BUFFER)
    buffered_routes = solve_lns(buffered_inst).routes
    buffered_check = check_decision(DATA / STRESS_INSTANCE, build_decision(medium, buffered_routes))
    assert buffered_check["feasible"], buffered_check["violations"]
    medium_plans["lns_buffer15"] = buffered_routes
    buffer_row = pl.DataFrame([{
        "plan": f"lns planned with travel x {BUFFER}",
        "nominal_total_travel_time": buffered_check["total_travel_time"],
        "vehicles_used": buffered_check["vehicles_used"],
        "feasible_on_true_times": buffered_check["feasible"],
    }])
    for name, path in scenario_files.items():
        per_scenario = run_stress_test(medium, medium_plans, path)
        per_scenario.write_csv(OUT / "stress" / f"per_scenario_{name}.csv")
        summary = summarize_stress(per_scenario)
        summary.write_csv(OUT / "stress" / f"summary_{name}.csv")
        stress_tables[name] = (per_scenario, summary)

    # Uniform slowdown each fixed medium plan tolerates before its first late start or late return.
    slowdown = pl.DataFrame([
        {"plan": m, "first_violation_at_uniform_slowdown": first_violation_factor(medium, medium_plans[m])}
        for m in ("rule", "lns")
    ])
    slowdown.write_csv(OUT / "stress" / "uniform_slowdown.csv")

    # 4. Held-out-size proxies (60 customers), both methods, every plan checked.
    proxy_rows = []
    for k in PROXY_SEEDS:
        folder = make_proxy(k, OUT / "proxies" / f"proxy{k}")
        inst = load_instance(folder)
        rule_routes = nearest_feasible_neighbor(inst)
        started = time.perf_counter()
        lns_routes = solve_lns(inst).routes
        seconds = time.perf_counter() - started
        checks = {m: check_decision(folder, build_decision(inst, r)) for m, r in (("rule", rule_routes), ("lns", lns_routes))}
        if not all(c["feasible"] for c in checks.values()):
            raise SystemExit(f"proxy{k}: a plan failed the checker {[c['violations'][:2] for c in checks.values()]}")
        proxy_rows.append({
            "proxy": f"proxy{k}", "customers": inst.n,
            "rule_travel": checks["rule"]["total_travel_time"], "lns_travel": checks["lns"]["total_travel_time"],
            "travel_saved_pct": 100 * (1 - checks["lns"]["total_travel_time"] / checks["rule"]["total_travel_time"]),
            "lns_seconds": seconds,
        })
    proxies = pl.DataFrame(proxy_rows)
    proxies.write_csv(OUT / "proxies.csv")

    # 5. Crossing analysis and maps for every instance and method.
    crossing_rows, crossing_counts = [], []
    (OUT / "maps").mkdir(exist_ok=True)
    for name in INSTANCES:
        inst = instances[name]
        fig, axes = plt.subplots(1, 2, figsize=(13, 6.5), layout="constrained")
        for ax, method in zip(axes, ("rule", "lns")):
            routes = plans[(name, method)]
            found = find_crossings(inst, routes)
            same = [c for c in found if c["kind"] == "same vehicle"]
            crossing_rows += [{"instance": name, "method": method, **c} for c in found]
            crossing_counts.append({
                "instance": name, "method": method,
                "within_a_route": len(same),
                "between_vehicles": len(found) - len(same),
                "within_route_uncross_feasible": sum(bool(c["uncross_feasible"]) for c in same),
            })
            m = measures(inst, routes)
            plot_routes_with_crossings(ax, inst, routes, found,
                                       f"{method.upper()}: {m['total_travel_time']:.1f} min, {m['vehicles_used']} vehicles")
        counts = {c["method"]: c for c in crossing_counts if c["instance"] == name}
        fig.suptitle(
            f"{name}: red circles = a route crossing itself, each tested by uncrossing it (2-opt). "
            f"Removable without missing a time window: rule {counts['rule']['within_route_uncross_feasible']} "
            f"of {counts['rule']['within_a_route']}, LNS {counts['lns']['within_route_uncross_feasible']} "
            f"of {counts['lns']['within_a_route']}", fontsize=10)
        fig.savefig(OUT / "maps" / f"{name}.png", dpi=150)
        if name == STRESS_INSTANCE:
            fig.savefig(OUT / "routes_medium.png", dpi=150)
        plt.close(fig)
    crossings = pl.DataFrame(crossing_rows, infer_schema_length=None)
    crossings.write_csv(OUT / "crossings.csv")
    crossing_summary = pl.DataFrame(crossing_counts)

    # 6. Plots.

    fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
    for name in INSTANCES[1:]:
        history = histories[name]
        rule_travel = comparison.filter((pl.col("instance") == name) & (pl.col("method") == "rule"))[
            "total_travel_time"].item()
        ax.plot(range(1, len(history) + 1), [h / rule_travel for h in history], label=name)
    ax.set_xlabel("LNS iteration (best so far)")
    ax.set_ylabel("Best travel / rule travel")
    ax.set_title("LNS convergence relative to the rule to beat")
    ax.legend()
    fig.savefig(OUT / "lns_convergence.png", dpi=150)
    plt.close(fig)

    fig, axes = plt.subplots(2, len(SETTINGS), figsize=(13, 7), layout="constrained", sharex="col")
    for col, (name, (per_scenario, _)) in enumerate(stress_tables.items()):
        top, bottom = axes[0][col], axes[1][col]
        for method in medium_plans:
            part = per_scenario.filter(pl.col("method") == method).sort("day_factor")
            top.plot(part["day_factor"], part["travel_time"], "o-", ms=4, color=COLORS[method], label=method)
            late = part.filter(pl.col("violations") > 0)
            top.scatter(late["day_factor"], late["travel_time"], s=70, facecolors="none",
                        edgecolors="black", zorder=5)
            offset = {"rule": -0.006, "lns": 0.0, "lns_buffer15": 0.006}[method]
            bottom.bar(part["day_factor"] + offset, part["violations"], width=0.006,
                       color=COLORS[method], label=method)
        mean, cv = SETTINGS[name]
        top.set_title(f"{name}: day factor mean {mean}, CV {cv} (circles = scenario with a violation)", fontsize=9)
        top.set_ylabel("Realized travel time (min)")
        bottom.set_ylabel("Late starts + late returns")
        bottom.set_xlabel("Scenario congestion factor (sorted)")
        top.legend()
        bottom.legend()
    fig.suptitle(f"Stress test of fixed plans on {STRESS_INSTANCE}: {N_SCENARIOS} saved scenarios each")
    fig.savefig(OUT / "stress_test.png", dpi=150)
    plt.close(fig)

    # 5. Markdown report used by the README.
    machine = f"{platform.platform()}, Python {platform.python_version()}, {platform.processor() or 'unknown CPU'}"
    lines = [
        "# Results (generated by `pixi run compare`)",
        "",
        f"Machine: {machine}. LNS defaults: seed {DEFAULT_SEED}, {DEFAULT_RESTARTS} run(s) x "
        f"{DEFAULT_ITERATIONS} iterations, 480 s safety cap.",
        "",
        "## Deterministic comparison",
        "",
        markdown_table(comparison),
        "",
        markdown_table(wide.select("instance", "customers", "total_travel_time_rule", "total_travel_time_lns",
                                   "travel_saved_pct", "vehicles_used_rule", "vehicles_used_lns",
                                   "seconds_rule", "seconds_lns"), 2),
        "",
        "Edge case:",
        "",
        markdown_table(edge_rows),
        "",
        "## Stress test (development_medium, fixed plans)",
        "",
        f"{N_SCENARIOS} scenarios per setting, seed {SCENARIO_SEED}. Travel time on arc (i, j) is multiplied "
        f"by a day-level congestion factor (lognormal) times road-level noise (lognormal, mean 1, CV {ARC_CV}).",
        "",
    ]
    lines += [
        f"Sensitivity plan `lns_buffer15`: the LNS planned on travel times x {BUFFER} (a congestion buffer), "
        "then executed on the scenario times like the other plans. Its cost on the true travel times:",
        "",
        markdown_table(buffer_row, 2),
        "",
    ]
    for name, (_, summary) in stress_tables.items():
        mean, cv = SETTINGS[name]
        lines += [f"### {name} (day factor mean {mean}, CV {cv})", "", markdown_table(summary, 2), ""]
    lines += [
        "### Uniform slowdown tolerance",
        "",
        "Every travel time multiplied by the same factor (steps of 0.01); the factor at which each fixed "
        "plan first has a late service start or a late return:",
        "",
        markdown_table(slowdown, 2),
        "",
        f"## Held-out-size proxies ({PROXY_SIZE} customers, random subsets of development_large, seeds 0-4)",
        "",
        markdown_table(proxies, 2),
        "",
        "## Route crossings (maps in results/maps/, every crossing in crossings.csv)",
        "",
        "Travel times equal the straight-line distance between the plotted coordinates, so these are real "
        "crossings. For each crossing inside a route, the 2-opt reversal that removes it was tested: "
        "`within_route_uncross_feasible` counts the ones that could be removed without breaking a constraint.",
        "",
        markdown_table(crossing_summary),
        "",
    ]
    lns_same = crossings.filter((pl.col("method") == "lns") & (pl.col("kind") == "same vehicle"))
    if lns_same.height:
        lines += [
            "Why each LNS within-route crossing stays (travel change if it were uncrossed, minutes):",
            "",
            markdown_table(lns_same.select("instance", "vehicle_1", "leg_1", "leg_2",
                                           "uncross_travel_change", "why_not"), 1),
            "",
        ]
    (OUT / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT / "run_info.json").write_text(json.dumps({"machine": machine}, indent=2), encoding="utf-8")
    print("Wrote results/RESULTS.md, CSV tables, decisions, and plots.")

    # Step 7: the scenario study runs last because it reads the stress scenarios saved in step 1.
    sys.path.insert(0, str(ROOT / "scripts"))
    import scenarios  # noqa: E402
    scenarios.main()


if __name__ == "__main__":
    main()
