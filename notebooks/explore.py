import marimo

__generated_with = "0.24.2"
app = marimo.App(width="full")


@app.cell
def _():
    import sys
    import time
    from pathlib import Path

    import marimo as mo
    import matplotlib.pyplot as plt
    import polars as pl

    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT / "src"))

    from vrptw.checker import check_decision
    from vrptw.crossings import find_crossings, plot_routes_with_crossings
    from vrptw.decision import build_decision, measures
    from vrptw.instance import InputError, load_instance, route_schedule
    from vrptw.lns import solve_lns
    from vrptw.rule import nearest_feasible_neighbor

    return (
        InputError, ROOT, build_decision, check_decision, find_crossings, load_instance, measures, mo,
        nearest_feasible_neighbor, pl, plot_routes_with_crossings, plt, route_schedule, solve_lns, time,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # OM 522 Option 3: delivery route planner

    Pick an instance, set the LNS budget, and press **Solve**. Both methods run on the same files,
    and the independent checker verifies both decisions. Expensive work only runs when the button
    is pressed.
    """)
    return


@app.cell
def _(ROOT, mo):
    data_root = ROOT / "data" / "option_03"
    instance_picker = mo.ui.dropdown(
        options=sorted(p.name for p in data_root.iterdir() if (p / "customers.csv").exists()),
        value="development_medium",
        label="Instance",
    )
    restarts = mo.ui.slider(1, 10, value=1, label="LNS runs")
    iterations = mo.ui.slider(500, 20000, step=500, value=8000, label="Iterations per run")
    seed = mo.ui.number(value=522, label="Seed")
    solve_button = mo.ui.run_button(label="Solve")
    mo.hstack([instance_picker, restarts, iterations, seed, solve_button], justify="start")
    return data_root, instance_picker, iterations, restarts, seed, solve_button


@app.cell
def _(
    InputError, data_root, instance_picker, iterations, load_instance, mo,
    nearest_feasible_neighbor, restarts, seed, solve_button, solve_lns, time,
):
    mo.stop(not solve_button.value, mo.md("Press **Solve** to run both methods."))
    folder = data_root / instance_picker.value
    try:
        inst = load_instance(folder)
    except InputError as _error:
        mo.stop(True, mo.callout(mo.md(f"**Input error:** {_error}"), kind="danger"))

    _t0 = time.perf_counter()
    _rule = nearest_feasible_neighbor(inst)
    _rule_seconds = time.perf_counter() - _t0
    _t0 = time.perf_counter()
    lns_result = solve_lns(inst, iterations=iterations.value, restarts=restarts.value, seed=int(seed.value))
    _lns_seconds = time.perf_counter() - _t0
    plans = {"rule": (_rule, _rule_seconds), "lns": (lns_result.routes, _lns_seconds)}
    return folder, inst, lns_result, plans


@app.cell
def _(build_decision, check_decision, folder, inst, mo, pl, plans):
    _rows = []
    for _method, (_routes, _seconds) in plans.items():
        if _routes is None:
            _rows.append({"method": _method, "feasible": False, "total_travel_time": None,
                          "vehicles_used": None, "waiting_time": None, "seconds": _seconds})
            continue
        _checked = check_decision(folder, build_decision(inst, _routes))
        # Raw values in the frame; only the table display formats them.
        _rows.append({"method": _method, "feasible": _checked["feasible"],
                      "total_travel_time": _checked["total_travel_time"],
                      "vehicles_used": _checked["vehicles_used"],
                      "waiting_time": _checked["waiting_time"],
                      "seconds": _seconds})
    comparison = pl.DataFrame(_rows)
    mo.vstack([mo.md("## Comparison (verified by the independent checker)"),
               mo.ui.table(comparison, selection=None,
                           format_mapping={"total_travel_time": "{:,.3f}", "waiting_time": "{:,.3f}",
                                           "seconds": "{:.2f}"})])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Route maps and crossings

    Travel times equal the straight-line distance between the plotted points, so a crossing here is
    real. Red circles mark a route crossing itself; the table below tests each one by uncrossing it
    (a 2-opt reversal). With time windows the reversal also reverses the visit order, so a crossing
    can stay in a good plan when removing it would make a customer late.
    """)
    return


@app.cell
def _(find_crossings, inst, measures, pl, plans, plot_routes_with_crossings, plt):
    _fig, _axes = plt.subplots(1, 2, figsize=(12, 6.5), layout="constrained")
    _rows = []
    for _ax, (_method, (_routes, _)) in zip(_axes, plans.items()):
        if _routes is None:
            _ax.set_title(f"{_method}: no feasible decision found")
            continue
        _found = find_crossings(inst, _routes)
        _rows += [{"method": _method, **c} for c in _found if c["kind"] == "same vehicle"]
        _m = measures(inst, _routes)
        plot_routes_with_crossings(_ax, inst, _routes, _found,
                                   f"{_method}: {_m['total_travel_time']:.1f} min travel, {_m['vehicles_used']} vehicles")
    crossing_table = pl.DataFrame(_rows, infer_schema_length=None) if _rows else pl.DataFrame()
    _fig
    return (crossing_table,)


@app.cell
def _(crossing_table, mo):
    mo.vstack([
        mo.md("**Crossings inside a route** (uncross_travel_change in minutes; negative = shorter)"),
        mo.ui.table(crossing_table.select("method", "vehicle_1", "leg_1", "leg_2", "uncross_feasible",
                                          "uncross_travel_change", "why_not"), selection=None)
        if crossing_table.height else mo.md("No route crosses itself."),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Vehicle timelines

    Each bar is one visit: grey is travel, yellow is waiting for the window to open, and green is
    service. The thin black line under each visit is the window during which service may START.
    A visit's own slack is the gap between its service start (where the green bar begins) and the end
    of its window line; how much delay a whole route absorbs also depends on the later stops and the
    shift end.
    """)
    return


@app.cell
def _(mo, plans):
    method_picker = mo.ui.radio(options=list(plans), value="lns", label="Timeline for")
    method_picker
    return (method_picker,)


@app.cell
def _(inst, method_picker, plans, plt, route_schedule):
    _routes = plans[method_picker.value][0] or []
    _used = [(v, r) for v, r in enumerate(_routes) if r]
    _fig, _ax = plt.subplots(figsize=(12, 0.45 * max(len(_used), 1) + 1.2), layout="constrained")
    for _row, (_v, _route) in enumerate(_used):
        _arrivals, _starts, _ret = route_schedule(inst, _v, _route)
        _clock, _prev = inst.shift_start[_v], 0
        for _c, _a, _s in zip(_route, _arrivals, _starts):
            _ax.barh(_row, _a - _clock, left=_clock, color="#bbbbbb", height=0.5)
            _ax.barh(_row, _s - _a, left=_a, color="#f2c14e", height=0.5)
            _ax.barh(_row, inst.service[_c], left=_s, color="#1b9e77", height=0.5)
            _ax.plot([inst.ws[_c], inst.we[_c]], [_row - 0.33, _row - 0.33], color="black", lw=1)
            _clock = _s + inst.service[_c]
        _ax.barh(_row, _ret - _clock, left=_clock, color="#bbbbbb", height=0.5)
    _ax.set_yticks(range(len(_used)), [inst.vehicle_ids[v] for v, _ in _used])
    _ax.invert_yaxis()
    _ax.set_xlabel("Minutes")
    _ax.set_title(f"{method_picker.value}: vehicle timelines")
    _fig
    return


@app.cell
def _(lns_result, plt):
    _fig, _ax = plt.subplots(figsize=(8, 3.5), layout="constrained")
    _ax.plot(range(1, len(lns_result.history) + 1), lns_result.history)
    _ax.set_xlabel("LNS iteration (all runs, best so far)")
    _ax.set_ylabel("Best total travel time")
    _ax.set_title(f"LNS convergence: started from {lns_result.start_method} at {lns_result.start_travel:.1f}; "
                  f"{lns_result.stop_reason}")
    _fig
    return


if __name__ == "__main__":
    app.run()
