# Gurobi MIP benchmark (labeled benchmark, not a graded method)

Two-index VRPTW MIP, warm-started with the LNS plan (MIP start), Gurobi seed 522; `time_limit_s` is each row's limit. Arcs are pruned only when no path from the depot can reach them in time. On these four instances that prunes exactly the same arcs as the earlier direct-leg test, so the rows below (run before the 2026-10-15 correction) are what the corrected model gives. `lns_max_saving_pct` = (LNS - lower bound) / LNS: the most of the LNS travel an optimal plan could save. `lns_max_above_optimal_pct` = (LNS - lower bound) / lower bound: the most the LNS travel can exceed the optimum. Both are 0 when the LNS plan is proven optimal.

| instance | customers | arcs | lns_travel | lns_seconds | time_limit_s | gurobi_status | gurobi_seconds | gurobi_travel | gurobi_feasible | gurobi_vehicles | lower_bound | gurobi_gap_pct | lns_max_saving_pct | lns_max_above_optimal_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hand_checkable | 6 | 29 | 329.670 | 0.491 | 60.000 | optimal | 0.003 | 329.670 | True | 2 | 329.670 | 0.000 | 0.000 | 0.000 |
| development_small | 15 | 157 | 459.094 | 0.824 | 60.000 | optimal | 0.066 | 459.094 | True | 4 | 459.094 | 0.000 | -0.000 | -0.000 |
| development_medium | 45 | 1215 | 1,040.678 | 6.423 | 300.000 | optimal | 37.456 | 1,040.678 | True | 8 | 1,040.678 | 0.000 | 0.000 | 0.000 |
| development_large | 120 | 8638 | 2,135.606 | 27.720 | 1,800.000 | time limit | 1,800.403 | 2,135.606 | True | 19 | 1,564.485 | 26.743 | 26.743 | 36.505 |
