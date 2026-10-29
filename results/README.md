# `results/`: everything the tool produced

Every file here (except this README) is written by `pixi run compare`. Don't edit them by hand. Rerun the command instead.

**Start with `RESULTS.md`.** It has all the tables in one place.

| Path | What it holds |
|---|---|
| `RESULTS.md` | All result tables in readable form |
| `comparison.csv`, `comparison_wide.csv` | Rule vs LNS on every instance: travel time, vehicles, runtime |
| `decisions/<instance>/<method>/` | The actual `decision.json` and `summary.json` behind each comparison row |
| `maps/`, `routes_medium.png` | Route maps for each instance, with crossings marked; `routes_medium.png` is the one shown in the main README |
| `crossings.csv` | Every route crossing and why it stays |
| `lns_convergence.png` | How the LNS travel time drops over its 8000 iterations |
| `proxies/`, `proxies.csv` | Five 60-customer test cases cut from `development_large`, standing in for the instructor's unseen 60-customer case |
| `stress/`, `stress_test.png` | Stress test: the 30 saved traffic scenarios (`.parquet`) and how each plan did |
| `scenarios/` | Management options (safety cushions, spare capacity) and `scenario_explorer.html`, an interactive page |
| `gurobi_benchmark.csv`, `GUROBI_BENCHMARK.md` | Optional Gurobi optimality check (made by `scripts/gurobi_benchmark.py`, not by `compare`) |
| `run_info.json` | Which computer produced these results |
