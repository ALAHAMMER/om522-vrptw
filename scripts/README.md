# `scripts/`: programs that produce the results

These use the solver in `src/vrptw/`. They are not part of `pixi run solve`.

| File | Run it with | What it does |
|---|---|---|
| `compare.py` | `pixi run compare` | **The one command that rebuilds everything in `results/`**: runs both methods on every instance, checks every plan with the checker, and writes the comparison tables, maps, stress test, and plots. Takes a few minutes. |
| `scenarios.py` | runs automatically at the end of `compare` (or alone with `pixi run scenarios`) | Extra plans for management, such as a 20-minute safety cushion before each window closes or trucks loaded to at most 85%. |
| `scenario_explorer.html` | used by `scenarios.py` | A web-page template. `scenarios.py` fills in the data and saves the finished page as `results/scenarios/scenario_explorer.html`. |
| `prototype_demo.py` | `pixi run prototype-demo` (add `--checks-only` for the rehearsal checks) | For the prototype video. Copies the medium instance to a new folder, runs both methods and the checker on it, and prints the saved comparison. `--checks-only` instead shows the bad-input rejections, the edge case, the worked example, a broken plan being caught, and the tests. Writes only under `out/`. |
| `gurobi_benchmark.py` | `pixi run -e benchmark gurobi-benchmark` | **Optional, not graded.** Solves the problem exactly with Gurobi to see how close the LNS gets to the best possible plan. Needs a personal Gurobi license. |
