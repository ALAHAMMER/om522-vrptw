import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium", app_title="OM 522 Option 3 walkthrough")


@app.cell
def _():
    import marimo as mo

    import csv
    import json
    import math
    import os
    import random
    import shutil
    import subprocess
    import sys
    import tempfile
    import time
    from pathlib import Path

    import matplotlib.pyplot as plt
    import numpy as np
    import polars as pl

    ROOT = Path(__file__).resolve().parents[1]
    DATA = ROOT / "data" / "option_03"
    RESULTS = ROOT / "results"
    sys.path.insert(0, str(ROOT / "src"))

    from vrptw import checker as checker_module
    from vrptw import lns as lns_module
    from vrptw import stress as stress_module
    from vrptw.decision import build_decision, measures
    from vrptw.instance import (
        MAX_EXACT_INTEGER,
        TOL,
        InputError,
        load_instance,
        route_is_feasible,
        route_travel,
    )
    from vrptw.lns import Route, local_search
    from vrptw.rule import nearest_feasible_neighbor

    return (
        DATA,
        InputError,
        MAX_EXACT_INTEGER,
        Path,
        RESULTS,
        ROOT,
        Route,
        TOL,
        build_decision,
        checker_module,
        csv,
        json,
        lns_module,
        load_instance,
        local_search,
        math,
        measures,
        mo,
        nearest_feasible_neighbor,
        np,
        os,
        pl,
        plt,
        random,
        route_is_feasible,
        route_travel,
        shutil,
        stress_module,
        subprocess,
        sys,
        tempfile,
        time,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # OM 522 Option 3: Vehicle Routing with Time Windows

    The next cell holds three small helpers. `run_command` runs a `pixi run` task's Python command
    in its own process, so we see the real exit code and messages. `show_run` prints that like a
    terminal. `agent_log_entry` shows a component's row from `AGENT_LOG.md`, read from the file so
    the two never disagree.
    """)
    return


@app.cell
def _(ROOT, mo, os, subprocess, sys, time):
    def run_command(args, drop_env=()):
        """Run `python -m <args>` with the settings Pixi uses; return what happened."""
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
        for name in drop_env:
            env.pop(name, None)
        started = time.perf_counter()
        done = subprocess.run(
            [sys.executable, "-m", *map(str, args)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return {
            "exit": done.returncode,
            "out": done.stdout.strip(),
            "err": done.stderr.strip(),
            "seconds": time.perf_counter() - started,
        }

    def show_run(command, result):
        """A terminal-style box for one command and its real output."""
        text = "\n".join(part for part in (result["out"], result["err"]) if part) or "(no output)"
        return mo.md(f"exit code `{result['exit']}`, {result['seconds']:.1f} s\n\n```text\n$ {command}\n{text}\n```")

    agent_log = {}
    for _line in (ROOT / "AGENT_LOG.md").read_text(encoding="utf-8").splitlines():
        if _line.startswith("| ") and _line[2].isdigit():
            _cells = [c.strip() for c in _line.strip()[1:-1].split(" | ")]
            agent_log[int(_cells[0])] = _cells

    def agent_log_entry(number):
        _, component, does, wrong, checked = agent_log[number]
        return mo.vstack([
            mo.md(f"**Agent-drafted component {number}: {component}**"),
            mo.callout(mo.md(f"**What it does.** {does}"), kind="neutral"),
            mo.callout(mo.md(f"**What was wrong or unclear in the agent's draft.** {wrong}"), kind="warn"),
            mo.callout(mo.md(f"**How we checked or fixed it.** {checked}"), kind="success"),
        ])

    return agent_log_entry, run_command, show_run


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1. Ingestion

    ### Instance settings

    `instance_name` picks one supplied instance. The guide asks the tool to run on a supplied
    instance directory *copied to a new path*, so the next cell makes that copy in the temp folder.
    The tool reads whatever folder it is given and never writes into it.
    """)
    return


@app.cell
def _(DATA):
    instance_name = "development_medium"
    supplied_dir = DATA / instance_name
    return instance_name, supplied_dir


@app.cell
def _(Path, instance_name, shutil, supplied_dir, tempfile):
    fresh_root = Path(tempfile.gettempdir()) / "om522_fresh_run"
    if fresh_root.exists():
        shutil.rmtree(fresh_root)  # only this notebook's own scratch folder

    fresh_dir = fresh_root / f"{instance_name}_copy"
    out_dir = fresh_root / "outputs"
    shutil.copytree(supplied_dir, fresh_dir)

    print(f" - {fresh_dir = }")
    print(f" - Files: {sorted(p.name for p in fresh_dir.iterdir())}")
    return fresh_dir, fresh_root, out_dir


@app.cell(hide_code=True)
def _(agent_log_entry):
    agent_log_entry(1)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### The required columns

    Each file's columns and declared types come from `DATA_DICTIONARY.md`. We check the files against
    this list instead of trusting whatever they contain, which is how a missing or misspelled column
    is caught.
    """)
    return


@app.cell
def _():
    REQUIRED_COLUMNS = {
        "depots.csv": {"node_id": "string", "x": "number", "y": "number"},
        "customers.csv": {
            "customer_id": "string",
            "x": "number",
            "y": "number",
            "demand": "integer",
            "service_time": "integer",
            "window_start": "integer",
            "window_end": "integer",
        },
        "vehicles.csv": {
            "vehicle_id": "string",
            "capacity": "integer",
            "shift_start": "integer",
            "shift_end": "integer",
        },
        "travel_times.csv": {"from_id": "string", "to_id": "string", "travel_time": "number"},
    }
    return (REQUIRED_COLUMNS,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Step 1. Read each file as text, then convert one column at a time

    The agent's first draft let Polars guess each column's type, so `capacity = sixty` crashed inside
    Polars with no column name. Reading everything as text (`infer_schema=False`) means we do the
    conversion ourselves, so every failure names its file and column. `strict=False` turns a value
    that is not a number into a null instead of a crash, and we report those nulls.
    """)
    return


@app.cell
def _(InputError, MAX_EXACT_INTEGER, pl):
    def read_checked(folder, name, columns):
        file = folder / name
        if not file.is_file():
            raise InputError(f"{name}: required file is missing from {folder}")
        try:
            raw = pl.read_csv(file, infer_schema=False)
        except Exception as error:
            raise InputError(f"{name}: file could not be read as CSV ({error})") from error

        out = []
        for column, kind in columns.items():
            if column not in raw.columns:
                raise InputError(f"{name}: required column '{column}' is missing")
            text = raw.get_column(column)
            if text.null_count() or (text.str.strip_chars() == "").any():
                raise InputError(f"{name}: column '{column}' has empty values")
            if kind == "string":
                out.append(text.str.strip_chars())
                continue

            number = text.str.strip_chars().cast(pl.Float64, strict=False)
            bad = number.is_null() | ~number.is_finite()
            if bad.any():
                example = text.filter(bad).head(3).to_list()
                article = "an" if kind == "integer" else "a"
                raise InputError(f"{name}: column '{column}' must be {article} {kind}; found {example}")

            if kind == "integer":
                if (number != number.round(0)).any():
                    example = text.filter(number != number.round(0)).head(3).to_list()
                    raise InputError(f"{name}: column '{column}' must be an integer; found {example}")
                # "60" converts exactly to Int64. "60.0" only converts through Float64, which is exact
                # below 2^53, so a larger value written with a decimal point is rejected, not rounded.
                exact = text.str.strip_chars().cast(pl.Int64, strict=False)
                too_big = exact.is_null() & (number.abs() >= MAX_EXACT_INTEGER)
                if too_big.any():
                    example = text.filter(too_big).head(3).to_list()
                    raise InputError(
                        f"{name}: column '{column}' has integers outside the supported range "
                        f"(64-bit integers, or magnitude below {MAX_EXACT_INTEGER:,} when written "
                        f"with a decimal point); found {example}"
                    )
                number = exact.fill_null(number.cast(pl.Int64))
            out.append(number.alias(column))
        return pl.DataFrame(out)

    return (read_checked,)


@app.cell
def _(REQUIRED_COLUMNS, fresh_dir, read_checked):
    tables = {
        name: read_checked(
            folder=fresh_dir,
            name=name,
            columns=columns,
        )
        for name, columns in REQUIRED_COLUMNS.items()
    }

    for _name, _frame in tables.items():
        print(f" - {_name}: {_frame.height:,} rows")

    tables["customers.csv"].head()
    return (tables,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Step 2. Check identifiers and values

    Each id must be unique, there must be exactly one depot, and a customer may not reuse the depot's
    id. Service times must be positive, demand and capacity must not be negative, and every window
    and shift must end no earlier than it starts.
    """)
    return


@app.cell
def _(InputError, pl, tables):
    depots_table = tables["depots.csv"]
    customers_table = tables["customers.csv"]
    vehicles_table = tables["vehicles.csv"]
    travel_table = tables["travel_times.csv"]

    for _name, _frame, _key in (
        ("depots.csv", depots_table, "node_id"),
        ("customers.csv", customers_table, "customer_id"),
        ("vehicles.csv", vehicles_table, "vehicle_id"),
    ):
        if _frame.get_column(_key).is_duplicated().any():
            _duplicates = _frame.filter(pl.col(_key).is_duplicated()).get_column(_key).unique().to_list()
            raise InputError(f"{_name}: column '{_key}' has duplicate identifiers {sorted(_duplicates)[:3]}")
    if depots_table.height != 1:
        raise InputError(f"depots.csv: column 'node_id' must list exactly one depot, found {depots_table.height}")
    depot = depots_table.item(0, "node_id")
    if depot in set(customers_table.get_column("customer_id").to_list()):
        raise InputError(f"customers.csv: column 'customer_id' reuses the depot id {depot}")

    if (customers_table.get_column("service_time") <= 0).any():
        raise InputError("customers.csv: column 'service_time' must be positive")
    if (customers_table.get_column("demand") < 0).any():
        raise InputError("customers.csv: column 'demand' must not be negative")
    if (customers_table.get_column("window_start") > customers_table.get_column("window_end")).any():
        raise InputError("customers.csv: column 'window_end' is earlier than 'window_start'")
    if (vehicles_table.get_column("capacity") < 0).any():
        raise InputError("vehicles.csv: column 'capacity' must not be negative")
    if (vehicles_table.get_column("shift_start") > vehicles_table.get_column("shift_end")).any():
        raise InputError("vehicles.csv: column 'shift_end' is earlier than 'shift_start'")
    if (travel_table.get_column("travel_time") < 0).any():
        raise InputError("travel_times.csv: column 'travel_time' must not be negative")

    print(f" - {depot = }")
    print(" - Every identifier and value check passed")
    return customers_table, depot, travel_table


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Step 3. Number the nodes and build the travel matrix

    The depot becomes node 0, and customers sorted by id become nodes 1 to n. The solvers can then
    use list positions instead of strings. Rows are matched **by identifier, never by row
    position**, so shuffled rows give the same answer. The matrix is filled with two joins and one
    vectorized assignment, and every ordered pair must appear exactly once.
    """)
    return


@app.cell
def _(InputError, customers_table, depot, np, pl, travel_table):
    sorted_customers = customers_table.sort("customer_id")
    ids = [depot, *sorted_customers.get_column("customer_id").to_list()]

    for _column in ("from_id", "to_id"):
        _unknown = set(travel_table.get_column(_column).unique().to_list()) - set(ids)
        if _unknown:
            raise InputError(f"travel_times.csv: column '{_column}' references unknown ids {sorted(_unknown)[:3]}")

    _size = len(ids)
    _index = pl.DataFrame({"id": ids, "i": np.arange(_size, dtype=np.int64)})
    _pairs = travel_table.join(
        _index.rename({"id": "from_id", "i": "a"}),
        on="from_id",
    ).join(
        _index.rename({"id": "to_id", "i": "b"}),
        on="to_id",
    )
    if _pairs.select(pl.struct("a", "b").is_duplicated().any()).item():
        raise InputError("travel_times.csv: column 'to_id' lists the same ordered pair more than once")
    if _pairs.height != _size * _size:
        raise InputError(
            f"travel_times.csv: column 'to_id' is missing ordered pairs ({_pairs.height} of {_size * _size} present)"
        )

    travel_matrix = np.zeros((_size, _size))
    travel_matrix[
        _pairs.get_column("a").to_numpy(),
        _pairs.get_column("b").to_numpy(),
    ] = _pairs.get_column("travel_time").to_numpy()

    print(f" - Nodes: {_size} (depot {ids[0]} plus {_size - 1} customers)")
    print(f" - Matrix shape: {travel_matrix.shape}")
    print(f" - Depot to {ids[1]}: {travel_matrix[0, 1]} minutes")
    return ids, travel_matrix


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Check: the same result as the module the solver uses

    `pixi run solve` calls `load_instance` in `src/vrptw/instance.py`. The steps above are the same
    logic laid out one step per cell, so they must give identical ids and an identical matrix. From
    here on, the notebook uses `inst`, the module's result.
    """)
    return


@app.cell
def _(fresh_dir, ids, load_instance, np, travel_matrix):
    inst = load_instance(fresh_dir)

    print(f" - Same node order: {ids == inst.ids}")
    print(f" - Same travel matrix: {np.array_equal(travel_matrix, inst.T_np)}")
    return (inst,)


@app.cell(hide_code=True)
def _(inst, math, mo):
    _total_demand = sum(inst.demand)
    _capacity = max(inst.cap)
    mo.md(f"""
    The instance has **{inst.n} customers** and **{len(inst.vehicle_ids)} vehicles**. Customers order
    **{_total_demand} units** in total. With {_capacity} units per vehicle, any feasible plan needs at least
    **{math.ceil(_total_demand / _capacity)} vehicles**.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Check: a malformed copy is rejected

    The guide requires three things for malformed input: a message naming the file and column, no
    `decision.json`, and a nonzero exit code. We copy an instance, set every capacity to the word
    "sixty" (the case that crashed the agent's draft), and run the real solve command. The copy goes
    in the same temp folder as the fresh copy, so it is cleared on the next run.
    """)
    return


@app.cell
def _(DATA, fresh_root, pl, run_command, shutil, show_run):
    _bad = fresh_root / "malformed"
    shutil.copytree(DATA / "development_small", _bad / "instance")
    _file = _bad / "instance" / "vehicles.csv"
    pl.read_csv(_file).with_columns(pl.lit("sixty").alias("capacity")).write_csv(_file)

    _result = run_command(["vrptw.cli", _bad / "instance", _bad / "out"])
    print(f" - decision.json written: {(_bad / 'out' / 'decision.json').exists()}")
    show_run("pixi run solve <bad copy> <out>", _result)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 2. Method 1: the rule to beat
    """)
    return


@app.cell(hide_code=True)
def _(agent_log_entry):
    agent_log_entry(2)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Nearest feasible neighbor

    Vehicles go out one at a time, in id order. From its current stop, each vehicle moves to the
    **nearest unserved customer by travel time** that passes three tests: it fits the remaining
    capacity, service can start by the window end, and the vehicle can still get back by its shift
    end. Ties go to the lower customer id. When no customer passes, the vehicle returns to the depot
    and the next one starts. A customer left over at the end means no feasible decision.
    """)
    return


@app.cell
def _(TOL):
    def rule_to_beat(inst):
        T, ws, we, service, demand, ids = inst.T, inst.ws, inst.we, inst.service, inst.demand, inst.ids
        unserved = set(range(1, inst.n + 1))
        routes = [[] for _ in inst.vehicle_ids]

        for v in range(len(inst.vehicle_ids)):
            clock, current, load = inst.shift_start[v], 0, 0
            while unserved:
                best_key, best_customer, best_start = None, None, 0.0
                for c in unserved:
                    if load + demand[c] > inst.cap[v]:
                        continue  # does not fit the remaining capacity
                    arrival = clock + T[current][c]
                    if arrival > we[c] + TOL:
                        continue  # cannot start service by the window end
                    start = max(arrival, ws[c])  # wait if early
                    if start + service[c] + T[c][0] > inst.shift_end[v] + TOL:
                        continue  # could not return by the shift end
                    key = (T[current][c], ids[c])  # nearest first, ties by customer id
                    if best_key is None or key < best_key:
                        best_key, best_customer, best_start = key, c, start
                if best_customer is None:
                    break  # this vehicle returns to the depot
                routes[v].append(best_customer)
                unserved.remove(best_customer)
                clock = best_start + service[best_customer]
                current = best_customer
                load += demand[best_customer]
            if not unserved:
                break

        return None if unserved else routes

    return (rule_to_beat,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Check: the worked example

    The instructor's `worked-example/` folder applies the rule to `hand_checkable` by hand. Our routes
    must match it stop for stop, and the total travel time must be **352.417**.
    """)
    return


@app.cell
def _(DATA, build_decision, checker_module, json, load_instance, pl, rule_to_beat):
    _hand = load_instance(DATA / "hand_checkable")
    _ours = build_decision(_hand, rule_to_beat(_hand))
    _expected = json.loads((DATA / "worked-example" / "solution.json").read_text(encoding="utf-8"))
    _total = checker_module.check_decision(DATA / "hand_checkable", _ours)["total_travel_time"]

    print(f" - Total travel time: {_total:.3f} (the brief says 352.417)")
    pl.DataFrame([
        {
            "vehicle": a["vehicle_id"],
            "our visits": " → ".join(a["visits"]),
            "worked example": " → ".join(b["visits"]),
            "same": a["visits"] == b["visits"],
            "our return": a["return_time"],
            "expected return": b["return_time"],
        }
        for a, b in zip(_ours["routes"], _expected["routes"])
    ])
    return


@app.cell
def _(inst, measures, nearest_feasible_neighbor, rule_to_beat):
    rule_routes = rule_to_beat(inst)
    _m = measures(inst, rule_routes)

    print(f" - Same routes as src/vrptw/rule.py: {rule_routes == nearest_feasible_neighbor(inst)}")
    print(f" - Total travel time: {_m['total_travel_time']:,.3f} minutes")
    print(f" - Vehicles used: {_m['vehicles_used']}")
    return (rule_routes,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3. The independent checker
    """)
    return


@app.cell(hide_code=True)
def _(agent_log_entry):
    agent_log_entry(6)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Recompute everything from the visit lists

    The checker uses only the Python standard library and the two things the instructor's checker
    sees: the input CSVs and `decision.json`. It walks each route from the depot and recomputes every
    arrival, wait, and load. It reports every broken window, late return, over-capacity vehicle, and
    customer missed or served twice. Reported times are **not** trusted; a mismatch is only a warning.
    """)
    return


@app.cell
def _(Path, TOL, csv):
    def read_rows(folder, name):
        with open(folder / name, newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def independent_check(instance_dir, decision):
        folder = Path(instance_dir)
        customers = {r["customer_id"].strip(): r for r in read_rows(folder, "customers.csv")}
        vehicles = {r["vehicle_id"].strip(): r for r in read_rows(folder, "vehicles.csv")}
        depot = read_rows(folder, "depots.csv")[0]["node_id"].strip()
        travel = {
            (r["from_id"].strip(), r["to_id"].strip()): float(r["travel_time"])
            for r in read_rows(folder, "travel_times.csv")
        }

        violations, warnings = [], []
        visits_count, vehicles_seen = {}, set()
        total_travel = waiting = 0.0
        vehicles_used = 0

        for route in decision.get("routes", []):
            vid = route.get("vehicle_id")
            if vid not in vehicles:
                violations.append(f"route uses unknown vehicle {vid}")
                continue
            if vid in vehicles_seen:
                violations.append(f"vehicle {vid} makes more than one route")
            vehicles_seen.add(vid)
            vehicle = vehicles[vid]
            visits = route.get("visits", [])
            if any(c not in customers for c in visits):
                violations.append(f"{vid}: visits unknown customers {[c for c in visits if c not in customers]}")
                continue
            if visits:
                vehicles_used += 1

            clock, previous, load = float(vehicle["shift_start"]), depot, 0
            arrivals, starts = [], []
            for c in visits:
                visits_count[c] = visits_count.get(c, 0) + 1
                customer = customers[c]
                leg = travel[(previous, c)]
                total_travel += leg
                arrival = clock + leg
                start = max(arrival, float(customer["window_start"]))
                waiting += start - arrival
                if start > float(customer["window_end"]) + TOL:
                    violations.append(
                        f"{vid}: service at {c} starts at {start:.6f}, after its window end {customer['window_end']}"
                    )
                load += int(float(customer["demand"]))
                arrivals.append(arrival)
                starts.append(start)
                clock, previous = start + float(customer["service_time"]), c
            if visits:
                total_travel += travel[(previous, depot)]
                return_time = clock + travel[(previous, depot)]
            else:
                return_time = float(vehicle["shift_start"])
            if return_time > float(vehicle["shift_end"]) + TOL:
                violations.append(f"{vid}: returns at {return_time:.6f}, after shift end {vehicle['shift_end']}")
            if load > int(float(vehicle["capacity"])):
                violations.append(f"{vid}: load {load} exceeds capacity {vehicle['capacity']}")

            # Reported times are not trusted, but a mismatch signals a bug in the writer.
            for label, reported, computed in (
                ("arrivals", route.get("arrivals"), arrivals),
                ("service_starts", route.get("service_starts"), starts),
            ):
                if reported is not None and (
                    len(reported) != len(computed) or any(abs(r - c) > 1e-6 for r, c in zip(reported, computed))
                ):
                    warnings.append(f"{vid}: reported {label} differ from recomputed values")
            if "return_time" in route and abs(route["return_time"] - return_time) > 1e-6:
                warnings.append(f"{vid}: reported return_time differs from recomputed value")

        unserved = sorted(set(customers) - set(visits_count))
        repeated = sorted(c for c, k in visits_count.items() if k > 1)
        if unserved:
            violations.append(f"customers not served: {unserved}")
        if repeated:
            violations.append(f"customers served more than once: {repeated}")

        return {
            "feasible": not violations,
            "violations": violations,
            "warnings": warnings,
            "total_travel_time": total_travel,
            "vehicles_used": vehicles_used,
            "waiting_time": waiting,
            "customers_served": sum(visits_count.values()),
        }

    return (independent_check,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Check: it agrees with the module, and it catches a broken plan

    First, the rule's plan: the notebook checker and `src/vrptw/checker.py` must return the same
    result. Then a checker that never says "infeasible" proves nothing, so we break the worked
    example on purpose. We reverse vehicle 1's visits (missing windows) and drop customer C006.
    """)
    return


@app.cell
def _(build_decision, checker_module, fresh_dir, independent_check, inst, rule_routes):
    _decision = build_decision(inst, rule_routes)
    _ours = independent_check(fresh_dir, _decision)

    print(f" - Same result as src/vrptw/checker.py: {_ours == checker_module.check_decision(fresh_dir, _decision)}")
    print(f" - Feasible: {_ours['feasible']}")
    print(f" - Total travel time: {_ours['total_travel_time']:,.3f}")
    return


@app.cell
def _(DATA, independent_check, json):
    _broken = json.loads((DATA / "worked-example" / "solution.json").read_text(encoding="utf-8"))
    _broken["routes"][0]["visits"] = ["C004", "C002", "C003"]  # reversed: misses windows
    _broken["routes"][1]["visits"] = _broken["routes"][1]["visits"][:-1]  # drops C006

    _result = independent_check(DATA / "hand_checkable", _broken)
    print(f" - Feasible: {_result['feasible']}")
    for _violation in _result["violations"]:
        print(f" - {_violation}")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4. Method 2: large neighborhood search

    The LNS follows Ropke & Pisinger (2006). It builds a starting plan, improves it with local
    search, and then repeats **ruin and recreate**: remove a few customers, put them back in better
    places, and keep the result if it is good enough. It uses a fixed seed (522) and stops after a
    fixed number of iterations (8,000). Time is only a safety cap (480 s), so the same input always
    gives the same plan.
    """)
    return


@app.cell(hide_code=True)
def _(agent_log_entry):
    agent_log_entry(3)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### The O(1) insertion test

    The search asks, millions of times, whether customer $c$ fits between two stops without making
    any **later** stop late. Rechecking the whole route each time is slow, so each route stores two
    arrays, indexed by position (the depot is position 0):

    - `dep[k]`: when the vehicle leaves position $k$.
    - `latest[k]`: the latest service start at position $k$ that keeps every later stop on time.
      It is filled backwards from the shift end:

    $$\text{latest}_k = \min\left(b_{c_k},\ \text{latest}_{k+1} - t_{c_k, c_{k+1}} - s_{c_k}\right)$$

    Then inserting $c$ before position `pos` is feasible if $c$ starts by its own window end and the
    vehicle still reaches the next stop by `latest[pos + 1]`. An off-by-one here would quietly allow
    late deliveries.
    """)
    return


@app.cell
def _():
    def route_times(inst, v, seq):
        T, ws, we, service = inst.T, inst.ws, inst.we, inst.service
        nodes = [0, *seq, 0]
        m = len(nodes)

        dep = [0.0] * m
        dep[0] = inst.shift_start[v]
        for k in range(1, m - 1):
            c = nodes[k]
            arrival = dep[k - 1] + T[nodes[k - 1]][c]
            dep[k] = max(arrival, ws[c]) + service[c]

        latest = [0.0] * m
        latest[m - 1] = inst.shift_end[v]
        for k in range(m - 2, 0, -1):
            c = nodes[k]
            latest[k] = min(we[c], latest[k + 1] - T[c][nodes[k + 1]] - service[c])
        return dep, latest

    return (route_times,)


@app.cell
def _(TOL, math):
    def insertion_cost(inst, v, seq, dep, latest, load, c, pos):
        """Extra travel from inserting customer c before seq[pos]; inf if infeasible."""
        if load + inst.demand[c] > inst.cap[v]:
            return math.inf
        T = inst.T
        before = seq[pos - 1] if pos > 0 else 0
        after = seq[pos] if pos < len(seq) else 0

        arrival = dep[pos] + T[before][c]
        start = max(arrival, inst.ws[c])
        if start > inst.we[c] + TOL:
            return math.inf
        # Reaching the next stop by its latest start keeps the rest of the route feasible.
        if start + inst.service[c] + T[c][after] > latest[pos + 1] + TOL:
            return math.inf
        return T[before][c] + T[c][after] - T[before][after]

    return (insertion_cost,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Check: three ways, every possible insertion

    For every customer, every route of the rule's plan, and every position, we compare three answers:
    the notebook shortcut, the module's `Route.insertion_cost`, and a full forward pass through the
    whole new route. All three must agree every time.
    """)
    return


@app.cell
def _(Route, inst, insertion_cost, math, route_is_feasible, route_times, rule_routes):
    _tested = _agree_full = _agree_module = _feasible = 0
    for _v, _seq in enumerate(rule_routes):
        if not _seq:
            continue
        _dep, _latest = route_times(inst, _v, _seq)
        _load = sum(inst.demand[c] for c in _seq)
        _module_route = Route(inst, _v, list(_seq))
        for _c in range(1, inst.n + 1):
            if _c in _seq:
                continue
            for _pos in range(len(_seq) + 1):
                _cost = insertion_cost(inst, _v, _seq, _dep, _latest, _load, _c, _pos)
                _full = route_is_feasible(inst, _v, _seq[:_pos] + [_c] + _seq[_pos:])
                _tested += 1
                _agree_full += (_cost < math.inf) == _full
                _agree_module += _cost == _module_route.insertion_cost(_c, _pos)
                _feasible += _full

    print(f" - Insertions tested: {_tested:,} ({_feasible:,} feasible)")
    print(f" - Agree with the full forward pass: {_agree_full:,}")
    print(f" - Agree with src/vrptw/lns.py: {_agree_module:,}")
    return


@app.cell(hide_code=True)
def _(agent_log_entry):
    agent_log_entry(4)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Local search: 2-opt and relocate

    Local search tries small changes and keeps the first one that shortens travel and stays feasible.
    Two of its five moves are below; or-opt, swap, and 2-opt* follow the same pattern.

    **2-opt** reverses a segment of one route, as in the TSP meetings. With symmetric travel times,
    only the two boundary edges change, so the test costs O(1):

    $$\Delta = t_{a, j} + t_{i, b} - t_{a, i} - t_{j, b} < 0$$

    The agent's draft used this shortcut on every instance. With one-way (asymmetric) times, the
    reversed inner edges change too, so we compare the exact route cost instead.

    **Relocate** moves one customer to its cheapest feasible position in another route. Our data
    break the triangle inequality slightly (108 triples on `development_large`), so removing a
    customer can make the rest of its route **later**. We re-check the shortened route.
    """)
    return


@app.cell
def _(TOL, route_is_feasible, route_travel):
    def two_opt(inst, v, seq):
        """First improving segment reversal in one route, or None if there is none."""
        T = inst.T
        travel = route_travel(inst, seq)
        n = len(seq)
        for i in range(n - 1):
            a = seq[i - 1] if i > 0 else 0
            for j in range(i + 1, n):
                b = seq[j + 1] if j + 1 < n else 0
                candidate = seq[:i] + seq[i:j + 1][::-1] + seq[j + 1:]
                if inst.symmetric:
                    improves = T[a][seq[j]] + T[seq[i]][b] - T[a][seq[i]] - T[seq[j]][b] < -TOL
                else:
                    improves = route_travel(inst, candidate) < travel - TOL
                if improves and route_travel(inst, candidate) < travel - TOL and route_is_feasible(inst, v, candidate):
                    return candidate
        return None

    return (two_opt,)


@app.cell
def _(TOL, insertion_cost, route_is_feasible, route_times):
    def relocate(inst, routes):
        """Apply the first improving move of one customer to another route; True if one was made."""
        T = inst.T
        for x, r1 in enumerate(routes):
            for i, c in enumerate(r1):
                a = r1[i - 1] if i > 0 else 0
                b = r1[i + 1] if i + 1 < len(r1) else 0
                removal_gain = T[a][c] + T[c][b] - T[a][b]
                for y, r2 in enumerate(routes):
                    if y == x or not r2:
                        continue
                    dep, latest = route_times(inst, y, r2)
                    load = sum(inst.demand[k] for k in r2)
                    for pos in range(len(r2) + 1):
                        if insertion_cost(inst, y, r2, dep, latest, load, c, pos) < removal_gain - TOL:
                            shorter = r1[:i] + r1[i + 1:]
                            # The data break the triangle inequality slightly, so check the shortened route.
                            if not route_is_feasible(inst, x, shorter):
                                break
                            routes[x] = shorter
                            routes[y] = r2[:pos] + [c] + r2[pos:]
                            return True
        return False

    return (relocate,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Check: the same moves as the module, then the full local search

    On each route of the rule's plan, the notebook `two_opt` and the module's `_two_opt` must pick the
    same reversal. One `relocate` must make the same move as the module's `_relocate`. Then the
    module's full local search (all five moves) runs on the rule's plan, and the checker confirms the
    result is still feasible.
    """)
    return


@app.cell
def _(
    Route,
    build_decision,
    fresh_dir,
    independent_check,
    inst,
    lns_module,
    local_search,
    relocate,
    rule_routes,
    time,
    two_opt,
):
    _same_two_opt = 0
    for _v, _seq in enumerate(rule_routes):
        _ours = two_opt(inst, _v, _seq)
        _module = Route(inst, _v, list(_seq))
        _changed = lns_module._two_opt(inst, _module)
        _same_two_opt += (_ours is None and not _changed) or _ours == _module.seq
    print(f" - 2-opt: same move as the module on {_same_two_opt} of {len(rule_routes)} routes")

    _ours_plan = [list(s) for s in rule_routes]
    relocate(inst, _ours_plan)
    _module_plan = [Route(inst, v, list(s)) for v, s in enumerate(rule_routes)]
    lns_module._relocate(inst, _module_plan, set(range(len(_module_plan))))
    print(f" - Relocate: same move as the module: {_ours_plan == [r.seq for r in _module_plan]}")

    _plan = [Route(inst, v, list(s)) for v, s in enumerate(rule_routes)]
    _before = sum(r.travel for r in _plan)
    _started = time.perf_counter()
    local_search(inst, _plan)
    _seconds = time.perf_counter() - _started
    _after = sum(r.travel for r in _plan)
    _check = independent_check(fresh_dir, build_decision(inst, [r.seq for r in _plan]))
    print(f" - Full local search on the rule's plan: {_before:,.1f} -> {_after:,.1f} minutes in {_seconds:.2f} s")
    print(f" - Checker says feasible: {_check['feasible']}")
    return


@app.cell(hide_code=True)
def _(agent_log_entry):
    agent_log_entry(5)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Ruin and recreate

    Each iteration:

    1. **Ruin.** Remove $q$ customers (2 to 15), with one of three operators: random (30% of the
       time), related, i.e. close in distance and window (40%), or worst, i.e. the costliest detours (30%).
    2. **Recreate.** Put them back with regret insertion. The customer with the most to lose, if its
       best spot is taken, goes first. Then local search tidies the changed routes.
    3. **Accept or not** (simulated annealing). A shorter plan is always kept. A longer one is kept
       with probability $e^{-\Delta / T}$, so the search can climb out of a dead end.

    The agent's starting temperature (about 0.5 minutes) was so cold that the search almost never
    accepted a worse plan, and every seed got stuck at 1,047.6 on `development_medium`. We set it with
    the Ropke & Pisinger rule: a plan 0.5% worse than the start is accepted with probability 0.5.

    $$T_0 = \frac{0.005 \times \text{start travel}}{\ln 2}, \qquad T_{\text{it}} = T_0 \left(1 - \frac{\text{it}}{\text{iterations}}\right)$$

    Removing, inserting, local search, and the feasibility test are the module's functions, which
    we have already walked through. The loop itself is written out below.
    """)
    return


@app.cell
def _(Route, TOL, lns_module, local_search, math):
    def ruin_and_recreate(inst, start_plan, start_travel, iterations, rng):
        vehicles = range(len(inst.vehicle_ids))
        current, current_travel = start_plan, start_travel
        best, best_travel = start_plan, start_travel
        temperature0 = lns_module.WORSE_PCT * start_travel / math.log(2)
        max_remove = max(3, min(15, inst.n // 4))
        history = []

        for it in range(1, iterations + 1):
            if inst.n < 2:  # nothing to rearrange
                history.append(best_travel)
                continue
            trial = [Route(inst, v, current[v][:]) for v in vehicles]

            # 1. Ruin: remove q customers with one of three operators.
            q = rng.randint(2, max_remove)
            draw = rng.random()
            if draw < 0.3:
                operator = lns_module._random_removal
            elif draw < 0.7:
                operator = lns_module._related_removal
            else:
                operator = lns_module._worst_removal
            removed = operator(inst, trial, q, rng)
            removed_set = set(removed)
            shortened = []
            for v, r in enumerate(trial):
                if not removed_set.isdisjoint(r.seq):
                    r.seq = [c for c in r.seq if c not in removed_set]
                    r.refresh()
                    shortened.append(v)
            k_regret = rng.choice((2, 3))
            # A shortened route can break a window when travel times break the triangle inequality.
            if not lns_module._all_feasible(inst, trial, shortened):
                history.append(best_travel)
                continue

            # 2. Recreate: regret insertion, then local search on the changed routes.
            if lns_module.regret_insertion(inst, trial, removed, k=k_regret, rng=rng):
                changed = {v for v in vehicles if trial[v].seq != current[v]}
                local_search(inst, trial, changed)
                if not lns_module._all_feasible(inst, trial, changed):
                    history.append(best_travel)
                    continue
                trial_travel = sum(r.travel for r in trial)

                # 3. Accept: always if shorter, sometimes if longer (the temperature falls to zero).
                temperature = temperature0 * (1 - it / iterations)
                accept = trial_travel < current_travel - TOL or (
                    temperature > 0
                    and rng.random() < math.exp(-(trial_travel - current_travel) / temperature)
                )
                if accept:
                    current, current_travel = [r.seq[:] for r in trial], trial_travel
                    if trial_travel < best_travel - TOL:
                        best, best_travel = [r.seq[:] for r in trial], trial_travel
            history.append(best_travel)

        return best, best_travel, history

    return (ruin_and_recreate,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Check: identical to the module, and repeatable

    We start from the rule's plan after local search and run 300 iterations (the default is 8,000).
    The notebook loop and the module's `_ruin_and_recreate` get the same seed, so they must return the
    same plan. Running seed 522 again must give identical routes, because the instructor reruns our
    command and compares outputs. Seed 523 may give a different plan.
    """)
    return


@app.cell
def _(Route, inst, lns_module, local_search, math, plt, random, ruin_and_recreate, rule_routes):
    _start = [Route(inst, v, list(s)) for v, s in enumerate(rule_routes)]
    local_search(inst, _start)
    _start_plan = [r.seq[:] for r in _start]
    _start_travel = sum(r.travel for r in _start)
    _iterations = 300

    _ours = ruin_and_recreate(inst, _start_plan, _start_travel, _iterations, random.Random(522))
    _again = ruin_and_recreate(inst, _start_plan, _start_travel, _iterations, random.Random(522))
    _other = ruin_and_recreate(inst, _start_plan, _start_travel, _iterations, random.Random(523))
    _module = lns_module._ruin_and_recreate(inst, _start_plan, _start_travel, _iterations, random.Random(522), math.inf)

    print(f" - Start (rule + local search): {_start_travel:,.3f} minutes")
    print(f" - Seed 522: {_ours[1]:,.3f}; same plan as src/vrptw/lns.py: {_ours[0] == _module[0]}")
    print(f" - Seed 522 again: {_again[1]:,.3f}; identical routes: {_again[0] == _ours[0]}")
    print(f" - Seed 523: {_other[1]:,.3f}; identical routes: {_other[0] == _ours[0]}")

    _fig, _ax = plt.subplots(
        nrows=1,
        ncols=1,
        figsize=(8, 3),
    )
    _ax.plot(range(1, len(_ours[2]) + 1), _ours[2])
    _ax.set_xlabel("Iteration")
    _ax.set_ylabel("Best travel so far (min)")
    _ax.set_title("Seed 522, 300 iterations")
    _fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 5. Run the documented commands on the fresh copy

    These are the commands the instructor runs, on the copy made in section 1. You can paste them into
    a terminal, or press the button to run the same commands here. The LNS takes about 10 seconds
    on `development_medium`, so this is the one cell that waits for a button.
    """)
    return


@app.cell
def _(fresh_dir, mo, out_dir):
    commands = {
        "rule": f'pixi run solve "{fresh_dir}" "{out_dir / "rule"}" --method rule',
        "lns": f'pixi run solve "{fresh_dir}" "{out_dir / "lns"}"',
        "check rule": f'pixi run check "{fresh_dir}" "{out_dir / "rule" / "decision.json"}"',
        "check lns": f'pixi run check "{fresh_dir}" "{out_dir / "lns" / "decision.json"}"',
    }
    run_button = mo.ui.run_button(label="Run both methods and the checker")
    mo.vstack([mo.md("```bash\n" + "\n".join(commands.values()) + "\n```"), run_button])
    return commands, run_button


@app.cell
def _(commands, fresh_dir, mo, out_dir, run_button, run_command, show_run):
    mo.stop(not run_button.value, mo.md("Press the button, or run the commands in a terminal."))
    with mo.status.spinner(title="Running the rule, the LNS, and the checker"):
        runs = {
            "rule": run_command(["vrptw.cli", fresh_dir, out_dir / "rule", "--method", "rule"]),
            "lns": run_command(["vrptw.cli", fresh_dir, out_dir / "lns"]),
        }
        checks = {
            m: run_command(["vrptw.checker", fresh_dir, out_dir / m / "decision.json"])
            for m in ("rule", "lns")
            if runs[m]["exit"] == 0
        }
    mo.vstack([
        show_run(commands["rule"], runs["rule"]),
        show_run(commands["lns"], runs["lns"]),
        *(show_run(commands[f"check {m}"], checks[m]) for m in checks),
    ])
    return (checks,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### The decisions

    The table takes travel, vehicles, and waiting from the **checker's** output, so every number has
    been verified independently. The tabs list each method's `decision.json`, one row per vehicle with
    its visit order. Load is summed from `customers.csv`, so capacity can be checked by eye.
    """)
    return


@app.cell
def _(checks, fresh_dir, json, mo, out_dir, pl):
    mo.stop(len(checks) < 2, mo.md("Both methods must finish first."))
    _demand = dict(pl.read_csv(fresh_dir / "customers.csv").select("customer_id", "demand").iter_rows())
    _capacity = dict(pl.read_csv(fresh_dir / "vehicles.csv").select("vehicle_id", "capacity").iter_rows())

    _summary_rows, _tabs = [], {}
    for _m, _label in (("rule", "Rule to beat"), ("lns", "LNS")):
        _checked = json.loads(checks[_m]["out"])
        _summary = json.loads((out_dir / _m / "summary.json").read_text(encoding="utf-8"))
        _summary_rows.append({
            "method": _label,
            "checker says feasible": _checked["feasible"],
            "total travel (min)": _checked["total_travel_time"],
            "vehicles used": _checked["vehicles_used"],
            "waiting (min)": _checked["waiting_time"],
            "runtime (s)": _summary["computation_seconds"],
            "stop rule": _summary.get("stop_reason", ""),
        })
        _decision = json.loads((out_dir / _m / "decision.json").read_text(encoding="utf-8"))
        _tabs[_label] = mo.ui.table(
            pl.DataFrame([
                {
                    "vehicle": r["vehicle_id"],
                    "stops": len(r["visits"]),
                    "load / capacity": f"{sum(_demand[c] for c in r['visits'])} / {_capacity[r['vehicle_id']]}",
                    "return time (min)": r["return_time"],
                    "visit order": " → ".join(r["visits"]),
                }
                for r in _decision["routes"]
                if r["visits"]
            ]),
            selection=None,
            format_mapping={"return time (min)": "{:,.1f}"},
        )

    mo.vstack([
        mo.ui.table(
            pl.DataFrame(_summary_rows),
            selection=None,
            format_mapping={"total travel (min)": "{:,.3f}", "waiting (min)": "{:,.3f}", "runtime (s)": "{:.3f}"},
        ),
        mo.ui.tabs(_tabs),
    ])
    return


@app.cell
def _(checks, inst, json, mo, out_dir, plt):
    mo.stop(len(checks) < 2)
    _where = {node: k for k, node in enumerate(inst.ids)}
    _fig, _axes = plt.subplots(
        nrows=1,
        ncols=2,
        figsize=(11, 5.2),
        layout="constrained",
    )
    for _ax, _m in zip(_axes, ("rule", "lns")):
        _decision = json.loads((out_dir / _m / "decision.json").read_text(encoding="utf-8"))
        _checked = json.loads(checks[_m]["out"])
        for _route in _decision["routes"]:
            _nodes = [0, *(_where[c] for c in _route["visits"]), 0]
            _ax.plot([inst.x[k] for k in _nodes], [inst.y[k] for k in _nodes], lw=1.4, marker="o", ms=3)
        _ax.plot(inst.x[0], inst.y[0], "ks", ms=9)
        _ax.set_title(f"{_m}: {_checked['total_travel_time']:,.1f} min, {_checked['vehicles_used']} vehicles")
        _ax.set_aspect("equal")
        _ax.set_xticks([])
        _ax.set_yticks([])
    _fig
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 6. Comparison on all four supplied instances

    `pixi run compare` regenerates `results/comparison.csv`, and the checker verifies every row. We
    read the saved file, since rerunning the large instance takes about 30 seconds. Minutes saved and
    percent saved show how the gap grows with instance size, along with the LNS runtime.
    """)
    return


@app.cell
def _(RESULTS, pl):
    _raw = pl.read_csv(RESULTS / "comparison.csv")
    _rule = _raw.filter(pl.col("method") == "rule").select(
        "instance",
        "customers",
        pl.col("total_travel_time").alias("rule travel (min)"),
        pl.col("vehicles_used").alias("rule vehicles"),
    )
    _lns = _raw.filter(pl.col("method") == "lns").select(
        "instance",
        pl.col("total_travel_time").alias("LNS travel (min)"),
        pl.col("vehicles_used").alias("LNS vehicles"),
        pl.col("seconds").alias("LNS runtime (s)"),
    )
    _rule.join(_lns, on="instance").with_columns(
        (pl.col("rule travel (min)") - pl.col("LNS travel (min)")).alias("minutes saved"),
        (100 * (1 - pl.col("LNS travel (min)") / pl.col("rule travel (min)"))).alias("saving %"),
    ).sort("customers")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 7. Stress test: uncertain travel times
    """)
    return


@app.cell(hide_code=True)
def _(agent_log_entry):
    agent_log_entry(7)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### The scenario model

    Travel time is the input we vary. On day $s$, the time on road $(i, j)$ is multiplied by

    $$f_{sij} = \underbrace{d_s}_{\text{congestion that day}} \times \underbrace{a_{sij}}_{\text{that road}}$$

    Both factors are lognormal with **mean 1**: CV 0.2 for the day, CV 0.1 for the road. A lognormal
    with mean 1 needs

    $$\sigma^2 = \ln(1 + \text{CV}^2), \qquad \mu = -\sigma^2 / 2$$

    The agent's version used $\mu = 0$, which quietly makes every day slower than intended. Its road
    noise also took the geometric mean of the $i \to j$ and $j \to i$ draws, which shrank the CV to about
    0.07. Ours mirrors one triangle, so each road keeps CV 0.1 and is the same in both directions.
    """)
    return


@app.cell
def _(np):
    def lognormal_mean_one(rng, cv, size):
        sigma = np.sqrt(np.log(1.0 + cv**2))
        return rng.lognormal(mean=-(sigma**2) / 2.0, sigma=sigma, size=size)

    return (lognormal_mean_one,)


@app.cell
def _(lognormal_mean_one, np):
    _rng = np.random.default_rng(1)
    for _cv in (0.1, 0.2):
        _right = lognormal_mean_one(_rng, _cv, 1_000_000)
        _naive = _rng.lognormal(mean=0.0, sigma=np.sqrt(np.log(1 + _cv**2)), size=1_000_000)
        print(f" - CV {_cv}: mean {_right.mean():.4f}, CV {_right.std() / _right.mean():.4f}; with mu = 0 the mean is {_naive.mean():.4f}")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Generate the 30 days, and check them against the saved file

    The scenarios are made from a fixed seed and **saved before either plan runs**, so both plans
    face the same 30 days. Regenerating them here, in the same order, must reproduce the saved
    `results/stress/scenarios_base.parquet` exactly. The stress test always uses `development_medium`.
    """)
    return


@app.cell
def _(DATA, RESULTS, load_instance, lognormal_mean_one, np, stress_module):
    stress_inst = load_instance(DATA / "development_medium")
    _rng = np.random.default_rng(stress_module.SCENARIO_SEED)
    _size = len(stress_inst.ids)

    day = lognormal_mean_one(_rng, stress_module.DAY_CV, stress_module.N_SCENARIOS)
    _arc = lognormal_mean_one(_rng, stress_module.ARC_CV, (stress_module.N_SCENARIOS, _size, _size))
    _arc = np.triu(_arc) + np.triu(_arc, 1).transpose(0, 2, 1)  # mirror the upper triangle
    factor = day[:, None, None] * _arc

    _saved, _saved_day = stress_module.load_scenarios(stress_inst, RESULTS / "stress" / "scenarios_base.parquet")
    _off = ~np.eye(_size, dtype=bool)
    print(f" - {stress_module.SCENARIO_SEED = }, {factor.shape = }")
    print(f" - Identical to the saved file: {np.array_equal(factor, _saved)}")
    print(f" - Road noise: mean {_arc[:, _off].mean():.4f}, CV {_arc[:, _off].std() / _arc[:, _off].mean():.4f}")
    print(f" - Same in both directions: {np.array_equal(_arc, _arc.transpose(0, 2, 1))}")
    print(f" - Day factors from {day.min():.2f} to {day.max():.2f}")
    return factor, stress_inst


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Execute each fixed plan, day by day

    The brief's execution rule: follow each planned route in order and change nothing. A vehicle that
    arrives early still waits. Every service that starts after its window end, and every late return,
    is a violation.
    """)
    return


@app.cell
def _(TOL):
    def execute_fixed_plan(inst, routes, day_factor):
        T = (inst.T_np * day_factor).tolist()
        travel = 0.0
        late_starts = late_returns = 0
        for v, route in enumerate(routes):
            if not route:
                continue
            clock, previous = inst.shift_start[v], 0
            for c in route:
                travel += T[previous][c]
                arrival = clock + T[previous][c]
                start = max(arrival, inst.ws[c])
                if start > inst.we[c] + TOL:
                    late_starts += 1
                clock, previous = start + inst.service[c], c
            travel += T[previous][0]
            if clock + T[previous][0] > inst.shift_end[v] + TOL:
                late_returns += 1
        return {"travel_time": travel, "late_starts": late_starts, "late_returns": late_returns}

    return (execute_fixed_plan,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### Results on the submitted plans

    We run the two submitted `development_medium` decisions through all 30 days and summarize. The
    numbers must match `results/stress/summary_base.csv`.
    """)
    return


@app.cell
def _(RESULTS, execute_fixed_plan, factor, json, np, pl, stress_inst):
    _node = {node: k for k, node in enumerate(stress_inst.ids)}
    _vehicle = {vid: k for k, vid in enumerate(stress_inst.vehicle_ids)}
    _rows = []
    for _m in ("rule", "lns"):
        _decision = json.loads(
            (RESULTS / "decisions" / "development_medium" / _m / "decision.json").read_text(encoding="utf-8")
        )
        _routes = [[] for _ in stress_inst.vehicle_ids]
        for _r in _decision["routes"]:
            _routes[_vehicle[_r["vehicle_id"]]] = [_node[c] for c in _r["visits"]]
        _days = [execute_fixed_plan(stress_inst, _routes, factor[s]) for s in range(factor.shape[0])]
        _travel = np.array([d["travel_time"] for d in _days])
        _rows.append({
            "plan": _m,
            "mean travel (min)": _travel.mean(),
            "P90 travel (min)": pl.Series(_travel).quantile(0.9, interpolation="linear"),
            "days with a violation (of 30)": sum(d["late_starts"] + d["late_returns"] > 0 for d in _days),
            "late starts": sum(d["late_starts"] for d in _days),
            "late returns": sum(d["late_returns"] for d in _days),
        })

    _saved = pl.read_csv(RESULTS / "stress" / "summary_base.csv")
    _match = all(
        abs(_saved.filter(pl.col("method") == r["plan"]).item(0, "travel_mean") - r["mean travel (min)"]) < 1e-9
        for r in _rows
    )
    print(f" - Mean travel matches results/stress/summary_base.csv: {_match}")
    pl.DataFrame(_rows)
    return


@app.cell
def _(RESULTS, mo):
    mo.image(str(RESULTS / "stress_test.png"), width="100%")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 8. Management scenarios
    """)
    return


@app.cell(hide_code=True)
def _(agent_log_entry):
    agent_log_entry(11)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ### A planning copy with a cushion

    A manager may accept a little more travel for fewer late deliveries. We do not change the LNS.
    Instead we give it a *planning copy* of the instance: each window closes `buffer` minutes early
    (never before it opens), each shift ends `buffer` minutes early, and capacity can be scaled
    down. Only the planner sees this copy. Every plan is scored and checked on the **real**
    instance, so the real limits always hold.
    """)
    return


@app.cell
def _():
    import dataclasses

    def planning_copy(inst, buffer=0.0, cap_share=1.0):
        we = [inst.we[0]] + [max(inst.ws[c], inst.we[c] - buffer) for c in range(1, inst.n + 1)]
        ends = [e - buffer for e in inst.shift_end]
        caps = [int(c * cap_share) for c in inst.cap]
        return dataclasses.replace(inst, we=we, shift_end=ends, cap=caps)

    return (planning_copy,)


@app.cell
def _(DATA, RESULTS, independent_check, json, pl, planning_copy, stress_inst):
    _cushion = planning_copy(stress_inst, buffer=20)
    print(" - First five customers, real window end vs planning window end (20-minute cushion):")
    print(pl.DataFrame({
        "customer": stress_inst.ids[1:6],
        "window start": stress_inst.ws[1:6],
        "real end": stress_inst.we[1:6],
        "planning end": _cushion.we[1:6],
    }))

    _plan = json.loads((RESULTS / "scenarios" / "plans" / "buffer_20" / "decision.json").read_text(encoding="utf-8"))
    _check = independent_check(DATA / "development_medium", _plan)
    print(
        f" - The saved 20-minute-cushion plan, checked on the real files: feasible {_check['feasible']}, "
        f"{_check['total_travel_time']:,.1f} minutes, {_check['vehicles_used']} vehicles"
    )
    return


@app.cell
def _(RESULTS, mo, pl):
    mo.vstack([
        pl.read_csv(RESULTS / "scenarios" / "scenarios.csv").select(
            "label",
            "total_travel_time",
            "vehicles_used",
            "base_clean_days",
            "base_late_starts",
            "heavy_congestion_clean_days",
        ),
        mo.image(str(RESULTS / "scenarios" / "tradeoff.png"), width="100%"),
    ])
    return


if __name__ == "__main__":
    app.run()
