"""Decision scenarios for management: alternative plans that trade travel time for other goals.

Usage: pixi run compare runs this as its last step. `pixi run scenarios` reruns only this part
(it needs the stress scenarios that compare.py saves first). Writes everything under results/scenarios/.

The graded methods minimise total travel time only. A dispatcher's boss also cares about on-time
reliability, driver hours, spare room for late orders, and cost. This script builds alternative
plans for development_medium by running the SAME LNS (src/vrptw/lns.py, unchanged) on a planning
copy of the instance with tighter internal targets, then scores every plan on the TRUE instance:

    rule            the rule to beat (today's practice)
    min_travel      the LNS plan (proven optimal for travel by the Gurobi benchmark)
    buffer_<b>      plan as if every window closes b minutes early and every shift ends b minutes
                    early, so each delivery keeps at least b minutes of protection against delays
    spare_cap       plan each truck to 85% of capacity, leaving room for add-on orders
    buffer15_spare  15-minute protection plus 85% loading

Every plan is checked by the independent checker against the real input files, then executed
unchanged under the 30 saved stress scenarios (results/stress/*.parquet, written by compare.py).
"""

import dataclasses
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vrptw.checker import check_decision  # noqa: E402
from vrptw.decision import build_decision, measures, write_outputs  # noqa: E402
from vrptw.instance import Instance, load_instance, route_schedule  # noqa: E402
from vrptw.lns import solve_lns  # noqa: E402
from vrptw.rule import nearest_feasible_neighbor  # noqa: E402
from vrptw.stress import load_scenarios, execute_plan  # noqa: E402

DATA = ROOT / "data" / "option_03"
INSTANCE = "development_medium"
OUT = ROOT / "results" / "scenarios"
STRESS = ROOT / "results" / "stress"
SPARE_SHARE = 0.85   # spare-capacity plans load each truck to at most 85% of capacity
# A shorter driver day was considered and is impossible on this instance: C039 cannot open before
# minute 500, needs 18 minutes of service and 42.4 minutes back, so some truck returns at 560.4 or later.

# Plain-language labels for slides and the interactive page.
LABELS = {
    "rule": ("Today's rule", "Nearest feasible neighbour, one truck at a time"),
    "min_travel": ("Fewest miles", "LNS, minimum total travel (proven optimal)"),
    "buffer_10": ("10-min cushion", "Every stop planned at least 10 min before its window closes"),
    "buffer_20": ("20-min cushion", "Every stop planned at least 20 min before its window closes"),
    "buffer_30": ("30-min cushion", "Every stop planned at least 30 min before its window closes"),
    "spare_cap": ("Spare capacity", "Trucks loaded to at most 85%, room for add-on orders"),
    "buffer15_spare": ("Cushion + spare", "15-min cushion and 85% loading combined"),
}


def planning_copy(inst: Instance, buffer: float = 0.0, cap_share: float = 1.0) -> Instance:
    """A copy of the instance with tighter internal targets. Only the PLANNER sees this copy;
    every plan is scored and checked on the real instance, so the real limits always hold."""
    we = [inst.we[0]] + [max(inst.ws[c], inst.we[c] - buffer) for c in range(1, inst.n + 1)]
    ends = [e - buffer for e in inst.shift_end]
    caps = [int(c * cap_share) for c in inst.cap]
    return dataclasses.replace(inst, we=we, shift_end=ends, cap=caps)


def plan_measures(inst: Instance, routes: list[list[int]]) -> dict:
    """Measures a manager reads beyond travel time, all on the real instance."""
    base = measures(inst, routes)
    durations, jit_durations, slacks, loads = [], [], [], []
    for v, route in enumerate(routes):
        if not route:
            continue
        arrivals, starts, back = route_schedule(inst, v, route)
        durations.append(back - inst.shift_start[v])
        # Leaving later by the wait at the first stop changes no service time, so a driver who
        # leaves "just in time" is on the clock for that much less.
        jit_durations.append(back - inst.shift_start[v] - (starts[0] - arrivals[0]))
        slacks.extend(inst.we[c] - s for c, s in zip(route, starts))
        loads.append(sum(inst.demand[c] for c in route) / inst.cap[v])
    return {
        **base,
        "driver_hours": sum(durations) / 60,
        "driver_hours_jit": sum(jit_durations) / 60,
        "longest_day_hours": max(durations) / 60,
        "shortest_day_hours": min(durations) / 60,
        "min_slack": min(slacks),
        "p10_slack": float(np.quantile(slacks, 0.1)),
        "mean_slack": float(np.mean(slacks)),
        "avg_load_pct": 100 * float(np.mean(loads)),
        "max_load_pct": 100 * max(loads),
        "stops_per_truck": base["customers_served"] / base["vehicles_used"],
    }


def stress_measures(inst: Instance, routes: list[list[int]], setting: str) -> tuple[dict, list[dict]]:
    """Execute the fixed plan under the saved scenarios of one setting."""
    factor, day = load_scenarios(inst, STRESS / f"scenarios_{setting}.parquet")
    rows = [{"scenario": s, "day_factor": float(day[s]), **execute_plan(inst, routes, factor[s])}
            for s in range(factor.shape[0])]
    frame = pl.DataFrame(rows)
    n_days = frame.height
    summary = frame.select(
        pl.col("travel_time").mean().alias("travel_mean"),
        pl.col("travel_time").quantile(0.9, interpolation="linear").alias("travel_p90"),
        (pl.col("violations") == 0).sum().alias("clean_days"),
        pl.col("late_service_starts").sum().alias("late_starts"),
        pl.col("late_returns").sum().alias("late_returns"),
    ).row(0, named=True)
    summary["clean_day_pct"] = 100 * summary["clean_days"] / n_days
    summary["on_time_pct"] = 100 * (1 - summary["late_starts"] / (inst.n * n_days))
    return {f"{setting}_{k}": v for k, v in summary.items()}, rows


def main() -> None:
    inst = load_instance(DATA / INSTANCE)
    if not (STRESS / "scenarios_base.parquet").exists():
        sys.exit("Run `pixi run compare` first: it writes the stress scenarios this script reuses.")

    plans = {"rule": nearest_feasible_neighbor(inst)}
    settings = {  # name -> planning copy handed to the unchanged LNS
        "min_travel": inst,
        "buffer_10": planning_copy(inst, buffer=10),
        "buffer_20": planning_copy(inst, buffer=20),
        "buffer_30": planning_copy(inst, buffer=30),
        "spare_cap": planning_copy(inst, cap_share=SPARE_SHARE),
        "buffer15_spare": planning_copy(inst, buffer=15, cap_share=SPARE_SHARE),
    }
    for name, planning in settings.items():
        result = solve_lns(planning)
        if result.routes is None:
            print(f"{name}: no feasible plan under these targets; skipped")
            continue
        plans[name] = result.routes
        print(f"{name}: travel {result.travel:.3f} ({result.stop_reason})")

    rows, per_day, export = [], [], {}
    for name, routes in plans.items():
        decision = build_decision(inst, routes)
        checked = check_decision(DATA / INSTANCE, decision)  # independent check on the REAL files
        if not checked["feasible"]:
            sys.exit(f"{name}: plan fails the checker: {checked['violations'][:3]}")
        write_outputs(OUT / "plans" / name, decision, {"plan": name, **measures(inst, routes)})
        row = {"plan": name, "label": LABELS[name][0], "description": LABELS[name][1],
               **plan_measures(inst, routes)}
        for setting in ("base", "heavy_congestion"):
            summary, days = stress_measures(inst, routes, setting)
            row.update(summary)
            per_day.extend({"plan": name, "setting": setting, **d} for d in days)
        rows.append(row)
        export[name] = decision["routes"]

    table = pl.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    table.write_csv(OUT / "scenarios.csv")
    pl.DataFrame(per_day).write_csv(OUT / "scenarios_per_day.csv")
    write_json_for_page(inst, table, export, pl.DataFrame(per_day))
    plot_maps(inst, plans, table)
    plot_tradeoff(table)
    write_markdown(table)
    print(table.select("plan", "total_travel_time", "vehicles_used", "driver_hours_jit", "min_slack",
                       "base_on_time_pct", "base_clean_days", "heavy_congestion_on_time_pct"))


def write_markdown(table: pl.DataFrame) -> None:
    """SCENARIOS.md: the scenario table in the same style as results/RESULTS.md."""
    columns = {
        "label": "plan", "total_travel_time": "planned travel (min)", "vehicles_used": "trucks",
        "driver_hours": "driver hours", "driver_hours_jit": "driver hours, leave just in time",
        "min_slack": "smallest cushion (min)", "avg_load_pct": "avg load %",
        "base_travel_mean": "stress travel mean", "base_travel_p90": "stress travel P90",
        "base_clean_days": "days with no violation (of 30)", "base_late_starts": "late starts",
        "base_late_returns": "late returns", "heavy_congestion_clean_days": "heavy: days with no violation",
        "heavy_congestion_late_starts": "heavy: late starts",
    }
    shown = table.select([pl.col(k).alias(v) for k, v in columns.items()])
    rows = ["| " + " | ".join(shown.columns) + " |", "|" + "---|" * shown.width]
    rows += ["| " + " | ".join(f"{v:,.2f}" if isinstance(v, float) else str(v) for v in row) + " |"
             for row in shown.iter_rows()]
    lines = [
        "# Management scenarios (generated by `pixi run compare`)",
        "",
        f"Instance {INSTANCE}. Every plan comes from the unchanged LNS run on a planning copy with tighter "
        "internal targets, then is checked by the independent checker on the real input files and "
        "executed unchanged under the 30 saved stress scenarios (base: day factor mean 1.0, CV 0.2; "
        "heavy: mean 1.15, CV 0.3). Driver hours count from shift start to return; the just-in-time "
        "column subtracts the wait at each route's first stop, which changes no service time.",
        "",
        *rows,
        "",
        "A shorter driver day is impossible on this instance: C039 opens at minute 500, needs 18 "
        "minutes of service and 42.4 minutes back to the depot, so its truck returns at 560.4 or later.",
        "",
    ]
    (OUT / "SCENARIOS.md").write_text("\n".join(lines), encoding="utf-8")


def write_json_for_page(inst: Instance, table: pl.DataFrame, routes: dict, per_day: pl.DataFrame) -> None:
    """Everything the interactive scenario page needs, in one file."""
    nodes = [{"id": inst.ids[k], "x": inst.x[k], "y": inst.y[k],
              "ws": inst.ws[k] if k else None, "we": inst.we[k] if k else None,
              "demand": inst.demand[k], "service": inst.service[k]} for k in range(inst.n + 1)]
    days = {name: {s: g.sort("scenario").select("day_factor", "travel_time", "late_service_starts",
                                                   "late_returns").to_dicts()
                   for (s,), g in frame.group_by("setting")}
            for (name,), frame in per_day.group_by("plan")}
    vehicles = {inst.vehicle_ids[v]: {"capacity": inst.cap[v], "shift_start": inst.shift_start[v],
                                      "shift_end": inst.shift_end[v]} for v in range(len(inst.vehicle_ids))}
    payload = {"instance": INSTANCE, "fleet_size": len(inst.vehicle_ids), "nodes": nodes,
               "vehicles": vehicles, "plans": table.to_dicts(), "routes": routes, "days": days}
    text = json.dumps(payload)
    (OUT / "scenarios.json").write_text(text, encoding="utf-8")
    # The interactive page is the template with this data embedded (it cannot fetch files).
    template = (ROOT / "scripts" / "scenario_explorer.html").read_text(encoding="utf-8")
    (OUT / "scenario_explorer.html").write_text(template.replace("__PLAN_DATA__", text), encoding="utf-8")


def plot_maps(inst: Instance, plans: dict, table: pl.DataFrame) -> None:
    """One route map per plan, plus a grid of the four headline plans."""
    cmap = plt.get_cmap("tab20")
    info = {r["plan"]: r for r in table.to_dicts()}

    def draw(ax, name):
        for v, route in enumerate(plans[name]):
            if route:
                pts = [0, *route, 0]
                ax.plot([inst.x[k] for k in pts], [inst.y[k] for k in pts], "-o", ms=3, lw=1.4,
                        color=cmap(v % 20))
        ax.plot(inst.x[0], inst.y[0], "ks", ms=9)
        r = info[name]
        ax.set_title(f"{r['label']}: {r['total_travel_time']:,.1f} min, {r['vehicles_used']} trucks",
                     fontsize=11)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_aspect("equal")

    (OUT / "maps").mkdir(parents=True, exist_ok=True)
    for name in plans:
        fig, ax = plt.subplots(figsize=(6, 6))
        draw(ax, name)
        fig.tight_layout()
        fig.savefig(OUT / "maps" / f"{name}.png", dpi=160)
        plt.close(fig)
    headline = [n for n in ("rule", "min_travel", "buffer_20", "spare_cap") if n in plans]
    fig, axes = plt.subplots(1, len(headline), figsize=(5 * len(headline), 5.2))
    for ax, name in zip(axes, headline):
        draw(ax, name)
    fig.tight_layout()
    fig.savefig(OUT / "maps_headline.png", dpi=160)
    plt.close(fig)


def plot_tradeoff(table: pl.DataFrame) -> None:
    """Scorecard: one small bar chart per measure (each with its own axis), every plan on each."""
    rows = table.to_dicts()[::-1]  # first plan at the top
    panels = [
        ("total_travel_time", "Planned travel (min)", "{:,.0f}"),
        ("vehicles_used", "Trucks used", "{:d}"),
        ("base_clean_days", "Days with zero problems (of 30)", "{:d}"),
        ("base_late_starts", "Late deliveries (30 days)", "{:d}"),
    ]
    fig, axes = plt.subplots(1, len(panels), figsize=(15, 4.2), sharey=True)
    labels = [r["label"] for r in rows]
    for ax, (column, title, fmt) in zip(axes, panels):
        values = [r[column] for r in rows]
        colors = ["#eb6834" if r["plan"] == "rule" else "#2a78d6" for r in rows]
        ax.barh(labels, values, color=colors, height=0.62)
        for k, value in enumerate(values):
            ax.text(value, k, "  " + fmt.format(value), va="center", fontsize=9, color="#0b0b0b")
        ax.set_title(title, fontsize=11, loc="left")
        ax.set_xlim(0, max(values) * 1.22)
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(axis="x", colors="#52514e", labelsize=8)
        ax.grid(axis="x", alpha=0.25)
    fig.suptitle("Each plan on four measures (development_medium; stress test: 30 simulated days)",
                 x=0.01, ha="left", fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT / "tradeoff.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
