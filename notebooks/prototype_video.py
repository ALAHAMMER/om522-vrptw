import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium", app_title="OM 522 prototype video")


@app.cell(hide_code=True)
def _():
    # Setup: imports, folders, and three small helpers used by the buttons below.
    import marimo as mo

    import json
    import os
    import shutil
    import subprocess
    import sys
    import time
    from pathlib import Path

    import matplotlib.pyplot as plt
    import polars as pl

    ROOT = Path(__file__).resolve().parents[1]
    DATA = ROOT / "data" / "option_03"
    RESULTS = ROOT / "results"
    VIDEO = ROOT / "out" / "video"  # out/ is ignored by git; the supplied data are never touched

    def run_command(args):
        """Run `python -m <args>` exactly as the pixi tasks do; return exit code and messages."""
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
        started = time.perf_counter()
        done = subprocess.run([sys.executable, "-m", *map(str, args)], cwd=ROOT, env=env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        return {"exit": done.returncode, "out": done.stdout.strip(), "err": done.stderr.strip(),
                "seconds": time.perf_counter() - started}

    def rel(path):
        """A short, readable path for the screen (relative to the repository)."""
        return Path(path).relative_to(ROOT).as_posix()

    def table(header, rows):
        """A plain Markdown table, which reads well on a recording."""
        lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        lines += ["| " + " | ".join(str(x) for x in row) + " |" for row in rows]
        return mo.md("\n".join(lines))

    def code_line(file, needle, meaning):
        """Show the one real source line that contains `needle`, with its line number and meaning."""
        lines = (ROOT / file).read_text(encoding="utf-8").splitlines()
        number = next(i for i, line in enumerate(lines, 1) if needle in line)
        return mo.vstack([
            mo.md(f"`{file}`, line {number}:"),
            mo.md(f"```python\n{lines[number - 1].strip()}\n```"),
            mo.md(f"*In plain English: {meaning}*"),
        ])

    return DATA, RESULTS, VIDEO, code_line, json, mo, pl, plt, rel, run_command, shutil, table, time


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Delivery Route Planner
    **OM 522 · Option 3 · Deterministic prototype**

    ## The decision

    Every morning a dispatcher decides **which truck visits which customers, and in what order**.

    - Each truck leaves the depot at the start of its shift, carries a limited load, and must be back by the end of its shift.
    - Each customer accepts a delivery only if service starts inside its **time window**.
    - A good plan serves every customer on time with the **least total travel time**. We also report the **number of trucks used**.

    Our tool reads the day's files, plans the routes **two ways**, checks both plans with a **separate checker**, and compares them.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    copy_button = mo.ui.run_button(label="Make a fresh copy of the data")
    mo.vstack([
        mo.md("## Step 1 · A fresh copy of the data\n"
              "We copy the instructor's 45-customer case to a **brand-new folder**. "
              "The tool reads any folder in this format without changing any code."),
        copy_button,
    ])
    return (copy_button,)


@app.cell(hide_code=True)
def _(DATA, VIDEO, copy_button, mo, pl, rel, shutil, table, time):
    fresh = None
    if copy_button.value:
        fresh = VIDEO / f"fresh_medium_{time.strftime('%H%M%S')}"
        shutil.copytree(DATA / "development_medium", fresh)
        _rows = [(f.name, pl.read_csv(f).height) for f in sorted(fresh.glob("*.csv"))]
        _step1 = mo.vstack([
            mo.callout(mo.md(f"New folder: **`{rel(fresh)}`**"), kind="success"),
            table(["File", "Rows"], _rows),
            mo.md("First five customers:"),
            table(["customer", "demand", "service time", "window opens", "window closes"],
                  pl.read_csv(fresh / "customers.csv")
                  .select("customer_id", "demand", "service_time", "window_start", "window_end")
                  .head(5).rows()),
        ])
    else:
        _step1 = mo.md("*Press the button to make the copy.*")
    _step1
    return (fresh,)


@app.cell(hide_code=True)
def _(mo):
    rule_button = mo.ui.run_button(label="Run method 1: the rule to beat")
    lns_button = mo.ui.run_button(label="Run method 2: our researched method")
    mo.vstack([
        mo.md("## Step 2 · Plan the routes two ways\n"
              "Both methods read the **same fresh copy**. Each button runs the documented "
              "`pixi run solve` command and shows what it wrote."),
        mo.hstack([
            mo.vstack([
                mo.md("**Method 1: the rule to beat** (given by the instructor)\n\n"
                      "Take the trucks one at a time. Each truck keeps driving to the **closest** customer "
                      "that still fits in the truck, can be reached before the window closes, and still lets "
                      "the truck get home on time. When nobody fits, the next truck starts."),
                rule_button,
            ]),
            mo.vstack([
                mo.md("**Method 2: large neighborhood search** (Ropke & Pisinger, 2006)\n\n"
                      "1. Build a good starting plan.\n"
                      "2. Make small fixes that keep every rule.\n"
                      "3. Remove a few customers and reinsert them in better places.\n"
                      "4. Repeat step 3 **8,000 times** and keep the best legal plan.\n\n"
                      "Fixed seed **522**, so every run gives the same plan."),
                lns_button,
            ]),
        ], widths="equal", gap=2, align="start"),
    ])
    return lns_button, rule_button


@app.cell(hide_code=True)
def _(fresh, json, mo, rel, rule_button, run_command):
    rule_out = None
    if fresh is None:
        _view = mo.md("*Make the fresh copy first (Step 1).*")
    elif rule_button.value:
        rule_out = fresh.parent / f"{fresh.name}_rule"
        _run = run_command(["vrptw.cli", fresh, rule_out, "--method", "rule"])
        _s = json.loads((rule_out / "summary.json").read_text())
        _view = mo.vstack([
            mo.md(f"Command: `pixi run solve {rel(fresh)} {rel(rule_out)} --method rule`"),
            mo.hstack([
                mo.stat(f"{_s['total_travel_time']:,.1f} min", label="Total travel time", bordered=True),
                mo.stat(str(_s["vehicles_used"]), label="Trucks used", bordered=True),
                mo.stat(f"{_s['computation_seconds']:.4f} s", label="Computation time", bordered=True),
            ], widths="equal"),
            mo.md(f"Status: **{_s['status']}** · exit code {_run['exit']} · stops when every customer is "
                  f"served or every truck has gone home"),
        ])
    else:
        _view = mo.md("*Method 1 has not been run yet.*")
    _view
    return (rule_out,)


@app.cell(hide_code=True)
def _(fresh, json, lns_button, mo, rel, run_command):
    lns_out = None
    if fresh is None:
        _view = mo.md("*Make the fresh copy first (Step 1).*")
    elif lns_button.value:
        lns_out = fresh.parent / f"{fresh.name}_lns"
        with mo.status.spinner(title="Running 8,000 iterations (usually 5–30 seconds)..."):
            _run = run_command(["vrptw.cli", fresh, lns_out])
        _s = json.loads((lns_out / "summary.json").read_text())
        _view = mo.vstack([
            mo.md(f"Command: `pixi run solve {rel(fresh)} {rel(lns_out)}`"),
            mo.hstack([
                mo.stat(f"{_s['total_travel_time']:,.1f} min", label="Total travel time", bordered=True),
                mo.stat(str(_s["vehicles_used"]), label="Trucks used", bordered=True),
                mo.stat(f"{_s['computation_seconds']:.1f} s", label="Computation time", bordered=True),
            ], widths="equal"),
            table(["Seed", "Stopping rule", "Iterations run", "Safety time cap", "How it stopped"],
                  [(_s["seed"], f"{_s['iterations_per_run']:,} iterations", f"{_s['iterations_run_total']:,}",
                    f"{_s['time_cap_seconds']:.0f} s", _s["stop_reason"])]),
            mo.md(f"Status: **{_s['status']}** · exit code {_run['exit']}"),
        ])
    else:
        _view = mo.md("*Method 2 has not been run yet.*")
    _view
    return (lns_out,)


@app.cell(hide_code=True)
def _(fresh, json, lns_out, mo, pl, plt, rule_out):
    # Route maps of the two plans, drawn from the decision.json files just written.
    if fresh is None or rule_out is None or lns_out is None:
        _maps = mo.md("*The route maps appear here once both methods have run.*")
    else:
        _depot = pl.read_csv(fresh / "depots.csv").row(0, named=True)
        _xy = {r["customer_id"]: (r["x"], r["y"]) for r in pl.read_csv(fresh / "customers.csv").iter_rows(named=True)}
        _fig, _axes = plt.subplots(1, 2, figsize=(12, 5.4), facecolor="white")
        for _ax, _folder, _name in ((_axes[0], rule_out, "Rule to beat"), (_axes[1], lns_out, "Researched method")):
            _routes = json.loads((_folder / "decision.json").read_text())["routes"]
            _summary = json.loads((_folder / "summary.json").read_text())
            for _k, _route in enumerate(_routes):
                _pts = [(_depot["x"], _depot["y"])] + [_xy[c] for c in _route["visits"]] + [(_depot["x"], _depot["y"])]
                _ax.plot(*zip(*_pts), "-o", color=plt.cm.tab20(_k % 20), markersize=4, linewidth=1.6)
            _ax.plot(_depot["x"], _depot["y"], "*", color="black", markersize=16)
            _ax.set_title(f"{_name}: {_summary['total_travel_time']:,.1f} min, {_summary['vehicles_used']} trucks",
                          fontsize=13)
            _ax.set_xticks([])
            _ax.set_yticks([])
        _fig.tight_layout()
        _maps = mo.vstack([mo.md("Each colour is one truck. The black star is the depot."), mo.as_html(_fig)])
    _maps
    return


@app.cell(hide_code=True)
def _(mo):
    check_button = mo.ui.run_button(label="Check both plans")
    mo.vstack([
        mo.md("## Step 3 · The independent checker\n"
              "A separate program that **trusts nothing the methods report**. It reads only the original "
              "data files and each truck's list of stops, then recomputes every arrival, load, and return "
              "time itself. It uses no code from either method."),
        check_button,
    ])
    return (check_button,)


@app.cell(hide_code=True)
def _(check_button, fresh, json, lns_out, mo, rel, rule_out, run_command, table):
    if rule_out is None or lns_out is None:
        _view = mo.md("*Run both methods first (Step 2).*")
    elif check_button.value:
        _rows, _commands, _all_ok = [], [], True
        for _name, _folder in (("Rule to beat", rule_out), ("Researched method", lns_out)):
            _run = run_command(["vrptw.checker", fresh, _folder / "decision.json"])
            _c = json.loads(_run["out"])
            _all_ok = _all_ok and _c["feasible"]
            _rows.append((_name, "✅ yes" if _c["feasible"] else "❌ NO", len(_c["violations"]),
                          f"{_c['customers_served']} of 45", f"{_c['total_travel_time']:,.3f} min", _c["vehicles_used"]))
            _commands.append(f"`pixi run check {rel(fresh)} {rel(_folder)}/decision.json`")
        _view = mo.vstack([
            table(["Plan", "Feasible", "Broken rules", "Customers served", "Travel (recomputed)", "Trucks"], _rows),
            mo.callout(mo.md("**Both plans pass every rule**, and the recomputed numbers match what the methods reported."
                             if _all_ok else "**A plan failed the checker.**"), kind="success" if _all_ok else "danger"),
            mo.md("Commands: " + " · ".join(_commands)),
        ])
    else:
        _view = mo.md("*Press the button to check both plans.*")
    _view
    return


@app.cell(hide_code=True)
def _(RESULTS, json, mo, pl, table):
    _wide = pl.read_csv(RESULTS / "comparison_wide.csv")
    _machine = json.loads((RESULTS / "run_info.json").read_text())["machine"].split(",")[0]
    _rows = [
        (r["instance"].replace("development_", "").replace("_checkable", "-checkable"), r["customers"],
         f"{r['total_travel_time_rule']:,.1f}", f"{r['total_travel_time_lns']:,.1f}", f"**{r['travel_saved_pct']:.1f}%**",
         f"{r['vehicles_used_rule']} → {r['vehicles_used_lns']}", f"{r['seconds_lns']:.1f} s")
        for r in _wide.iter_rows(named=True)
    ]
    mo.vstack([
        mo.md("## Step 4 · Initial comparison on all four supplied cases\n"
              "Same files and the same measures for both methods. Every plan below passed the checker."),
        table(["Case", "Customers", "Rule travel (min)", "Our travel (min)", "Travel saved", "Trucks (rule → ours)",
               "Our runtime"], _rows),
        mo.md(f"The rule takes under 0.01 s on every case. Saved results from `pixi run compare` on one laptop "
              f"({_machine}), seed 522, 8,000 iterations, 480 s safety cap."),
        mo.callout(mo.md("**What it shows:** the saving grows with size, from about 6% on 6 customers to about 39% on 120, "
                         "because the rule's last trucks collect scattered leftovers. **Caution:** these are four practice "
                         "cases from one generator, not a promise for every day."), kind="info"),
    ])
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 5 · What the AI agent drafted, and how we checked it

    We built this tool with an AI coding agent (Claude Code). Each of us explains one part it drafted:
    **what it does**, **what was wrong or unclear** in the agent's version, and **how we checked it**.
    """)
    return


@app.cell(hide_code=True)
def _(code_line, mo):
    input_button = mo.ui.run_button(label="Run the check: give it two broken files")
    mo.vstack([
        mo.md("### A · The input reader (`instance.py`)"),
        mo.callout(mo.md("**What it does.** Before solving, it checks that every file and column is there, every value "
                         "has the right type, every ID exists, and service times are positive. If not, it stops and "
                         "names the file and column."), kind="neutral"),
        mo.callout(mo.md("**What was wrong in the agent's version.** Its first draft let the software *guess* each "
                         "column's type, so a capacity written as \"sixty\" crashed with a confusing error that didn't "
                         "say where the problem was. Now every column is read as text and checked by name."), kind="warn"),
        code_line("src/vrptw/instance.py", "required column '{column}' is missing",
                  "if a needed column is missing, stop and say which file and which column."),
        input_button,
    ])
    return (input_button,)


@app.cell(hide_code=True)
def _(DATA, VIDEO, input_button, mo, pl, run_command, shutil, table, time):
    if input_button.value:
        _stamp = time.strftime("%H%M%S")
        _cases = []
        # Broken copy 1: the window_end column deleted from customers.csv.
        _a = VIDEO / f"broken_missing_column_{_stamp}"
        shutil.copytree(DATA / "hand_checkable", _a)
        pl.read_csv(_a / "customers.csv").drop("window_end").write_csv(_a / "customers.csv")
        _cases.append(("window_end column deleted", _a))
        # Broken copy 2: the word "sixty" in the vehicles capacity column.
        _b = VIDEO / f"broken_bad_type_{_stamp}"
        shutil.copytree(DATA / "hand_checkable", _b)
        (pl.read_csv(_b / "vehicles.csv", infer_schema=False).with_columns(pl.lit("sixty").alias("capacity"))
         .write_csv(_b / "vehicles.csv"))
        _cases.append(("capacity written as \"sixty\"", _b))
        _rows = []
        for _what, _folder in _cases:
            _out = _folder.parent / f"{_folder.name}_out"
            _run = run_command(["vrptw.cli", _folder, _out])
            _rows.append((_what, f"`{_run['err']}`", _run["exit"],
                          "yes ❌" if (_out / "decision.json").exists() else "no ✅"))
        _view = mo.vstack([
            table(["Broken copy", "Message from the tool", "Exit code", "Plan written?"], _rows),
            mo.callout(mo.md("**Both rejected**, with the file and column named. No plan is written, and the exit code "
                             "is not zero."), kind="success"),
        ])
    else:
        _view = mo.md("*Press the button to run A's check.*")
    _view
    return


@app.cell(hide_code=True)
def _(code_line, mo):
    rule_check_button = mo.ui.run_button(label="Run the check: compare with the instructor's worked example")
    mo.vstack([
        mo.md("### B · The rule to beat (`rule.py`)"),
        mo.callout(mo.md("**What it does.** One truck at a time, it keeps going to the closest unserved customer that "
                         "fits the truck, can be reached before the window closes, and still lets the truck get home "
                         "on time."), kind="neutral"),
        mo.callout(mo.md("**What was unclear in the agent's version.** The word *nearest*: shortest drive, or earliest "
                         "arrival including waiting? The brief says **shortest travel time**, with ties going to the "
                         "lower customer ID."), kind="warn"),
        code_line("src/vrptw/rule.py", "nearest first, ties by customer id",
                  "rank customers by travel time from where the truck is now; a tie goes to the lower customer ID."),
        rule_check_button,
    ])
    return (rule_check_button,)


@app.cell(hide_code=True)
def _(DATA, VIDEO, json, mo, rule_check_button, run_command, shutil, table, time):
    if rule_check_button.value:
        _copy = VIDEO / f"fresh_hand_{time.strftime('%H%M%S')}"
        shutil.copytree(DATA / "hand_checkable", _copy)
        _out = _copy.parent / f"{_copy.name}_rule"
        run_command(["vrptw.cli", _copy, _out, "--method", "rule"])
        _ours = json.loads((_out / "decision.json").read_text())["routes"]
        _theirs = json.loads((DATA / "worked-example" / "solution.json").read_text())["routes"]
        _metrics = json.loads((DATA / "worked-example" / "metrics.json").read_text())
        _summary = json.loads((_out / "summary.json").read_text())
        _rows = [(o["vehicle_id"], " → ".join(o["visits"]), " → ".join(t["visits"]),
                  "✅" if o["visits"] == t["visits"] and o["vehicle_id"] == t["vehicle_id"] else "❌")
                 for o, t in zip(_ours, _theirs)]
        _rows.append(("**Total travel**", f"{_summary['total_travel_time']:.3f} min",
                      f"{_metrics['total_travel_time']:.3f} min",
                      "✅" if abs(_summary["total_travel_time"] - _metrics["total_travel_time"]) < 1e-6 else "❌"))
        _rows.append(("**Trucks used**", _summary["vehicles_used"], _metrics["vehicles_used"],
                      "✅" if _summary["vehicles_used"] == _metrics["vehicles_used"] else "❌"))
        _view = mo.vstack([
            table(["Truck", "Our rule", "Instructor's worked example", "Match"], _rows),
            mo.callout(mo.md("**Exact match**: same trucks, same stops in the same order, 352.417 minutes. "
                             "This is also one of our three required automated tests."), kind="success"),
        ])
    else:
        _view = mo.md("*Press the button to run B's check.*")
    _view
    return


@app.cell(hide_code=True)
def _(code_line, mo):
    broken_plan_button = mo.ui.run_button(label="Run the check: give it a broken plan")
    tests_button = mo.ui.run_button(label="Run all automated tests")
    mo.vstack([
        mo.md("### C · The independent checker (`checker.py`)"),
        mo.callout(mo.md("**What it does.** Rebuilds every plan from scratch using only the data files and each truck's "
                         "list of stops, and lists any broken rule. It uses no code from either method, so a bug in a "
                         "method can't hide inside it."), kind="neutral"),
        mo.callout(mo.md("**What was unclear in the agent's version.** Should it trust the arrival times a method writes "
                         "into its plan? **No.** The instructor's checker reads only the stops, so ours recomputes every "
                         "time and only warns if the written times disagree."), kind="warn"),
        code_line("src/vrptw/checker.py", 'start > float(customer["window_end"]) + TOL',
                  "if service would start after the customer's window closes, record it as a broken rule."),
        mo.hstack([broken_plan_button, tests_button], justify="start"),
    ])
    return broken_plan_button, tests_button


@app.cell(hide_code=True)
def _(DATA, VIDEO, broken_plan_button, json, mo, run_command, time):
    if broken_plan_button.value:
        _plan = json.loads((DATA / "worked-example" / "solution.json").read_text())
        _plan["routes"][0]["visits"] = _plan["routes"][0]["visits"][::-1]   # truck V01's route reversed
        _plan["routes"][1]["visits"] = _plan["routes"][1]["visits"][:-1]    # customer C006 removed
        VIDEO.mkdir(parents=True, exist_ok=True)
        _file = VIDEO / f"broken_plan_{time.strftime('%H%M%S')}.json"
        _file.write_text(json.dumps(_plan, indent=2))
        _c = json.loads(run_command(["vrptw.checker", DATA / "hand_checkable", _file])["out"])
        _view = mo.vstack([
            mo.md("We broke the instructor's plan on purpose: **truck V01's route reversed** and **customer C006 removed**."),
            mo.md(f"Feasible: **{'yes' if _c['feasible'] else 'no'}**. Broken rules found:"),
            mo.md("\n".join(f"- {v}" for v in _c["violations"])),
            mo.callout(mo.md("**Both problems caught**: the late starts at C002 and C003, and the missing C006."),
                       kind="success" if not _c["feasible"] else "danger"),
        ])
    else:
        _view = mo.md("*Press \"give it a broken plan\" to run C's check.*")
    _view
    return


@app.cell(hide_code=True)
def _(mo, run_command, tests_button):
    if tests_button.value:
        with mo.status.spinner(title="Running the automated tests..."):
            _run = run_command(["pytest", "-q", "tests"])
        _last = _run["out"].splitlines()[-1] if _run["out"] else _run["err"]
        _view = mo.callout(mo.md(f"`pixi run test`: **{_last}**. This includes the three required tests: the worked "
                                 "example, the infeasible edge case, and the deleted-column copy."),
                           kind="success" if _run["exit"] == 0 else "danger")
    else:
        _view = mo.md("")
    _view
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Next · Slower traffic

    For the final submission we test how both fixed plans hold up when the data are wrong.
    **The uncertain input is travel times (traffic).** We will generate **30 traffic days** from a fixed seed,
    save them to files first, run **both plans unchanged** through the same 30 days, and count
    **late deliveries and late returns**.
    """)
    return


if __name__ == "__main__":
    app.run()
