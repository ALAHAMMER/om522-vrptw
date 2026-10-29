# `src/vrptw/`: the actual program

This folder is the route planner itself. Everything else in the repo (scripts, notebooks, tests)
imports from here. `vrptw` stands for *vehicle routing problem with time windows*.

## What happens when you run `pixi run solve <input_dir> <output_dir>`

```
 cli.py                 the "solve" command; it calls the other files in this order
   │
   ├─ 1. instance.py    read the 4 CSV files and run the 4 input checks
   │                    (bad input stops here with "Input error: <file>: column ...", exit 2)
   │
   ├─ 2. rule.py        Method 1, the rule to beat          (if --method rule)
   │    or lns.py       Method 2, the researched method     (the default)
   │
   └─ 3. decision.py    write decision.json and summary.json to the output folder

 checker.py             a separate program (pixi run check) that re-reads the CSVs and
                        decision.json and recomputes everything. It imports nothing above.
```

## The files, in the order to read them

| # | File | Lines | What it does | Main function to look at |
|---|---|---|---|---|
| 1 | `instance.py` | 242 | Loads the data and runs the four input checks. Turns customer ids into numbers (depot = 0, customers = 1..n) so lookups are fast. Also computes one route's arrival times and checks whether a route is feasible. | `load_instance`, `route_schedule`, `route_is_feasible` |
| 2 | `rule.py` | 46 | **Method 1, the rule to beat.** Each vehicle in turn drives to the nearest customer it can still serve on time, until none fit. Short enough to trace by hand. | `nearest_feasible_neighbor` |
| 3 | `decision.py` | 60 | Turns a list of routes into `decision.json` and computes the measures (travel time, vehicles used, waiting). | `build_decision`, `measures` |
| 4 | `cli.py` | 135 | The `solve` command: reads the options, runs steps 1 to 3 above, and sets the exit code. | `main` |
| 5 | `checker.py` | 126 | **The independent checker.** Uses only plain Python (no code from this folder) so it can't share a bug with the solvers. | `check_decision` |
| 6 | `lns.py` | 490 | **Method 2, large neighborhood search.** The biggest file. Read it last (see the guide below). | `solve_lns` |
| 7 | `stress.py` | 133 | Stress test (final submission): 30 random "traffic days", then runs each fixed plan through them. | `generate_scenarios`, `execute_plan` |
| 8 | `crossings.py` | 113 | Extra analysis: finds where routes cross on the map and whether uncrossing them would break a time window. | `find_crossings` |

`__init__.py` is one line. It only tells Python that this folder is a package.

## Reading `lns.py` without getting lost

Read it from the bottom up. The top of the file holds small helpers, and the main loop is at the end.

1. `solve_lns`: the entry point. It builds a starting plan, then calls the loop below 8000 times.
2. `_ruin_and_recreate`: one iteration. Remove a few customers ("ruin"), put them back
   ("recreate"), improve with local search, and keep the result if it is good enough.
3. `_random_removal`, `_related_removal`, `_worst_removal`: three ways to pick which customers to remove.
4. `regret_insertion`: puts removed customers back, starting with the hardest to place.
5. `local_search` and its five moves: `_two_opt`, `_or_opt`, `_relocate`, `_swap`, `_two_opt_star`.
6. `class Route`: one vehicle's stop list, plus cached times that make "can I insert here?" a fast check.
