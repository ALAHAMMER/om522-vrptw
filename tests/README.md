# `tests/`: automated tests

Run all of them with `pixi run test`. Every test should print as a dot, and the last line should say `37 passed`.

## `test_required.py`: the three tests the project guide requires, plus extras

| Test | What it proves |
|---|---|
| `test_rule_reproduces_worked_example` | **Required test 1.** The rule gives exactly the worked example's routes, times, and total travel 352.417. |
| `test_edge_case_reports_no_feasible_decision` | **Required test 2.** `edge_case/` prints "no feasible decision found", writes no decision.json, and exits 0. |
| `test_missing_required_column_is_rejected` | **Required test 3.** A copy with a column deleted is rejected with the file and column named. |
| `test_other_malformed_inputs_are_rejected` | Other bad inputs (wrong type, unknown id, zero service time, ...) are rejected too. |
| `test_lns_is_feasible_and_beats_rule` | The LNS plan passes the checker and beats the rule. |
| `test_lns_is_deterministic` | Same input and seed give the same routes every time. |
| `test_shuffled_rows_give_the_same_decision` | Row order in the CSVs doesn't change the answer. |
| `test_heterogeneous_fleet_is_respected` | Trucks with different capacities and shifts are handled. |
| `test_checker_flags_a_broken_decision` | The checker actually catches a bad plan. |
| `test_route_duration_is_travel_plus_waiting_plus_service` | The reported measures add up. |

## `test_review_fixes.py`: regression tests

An independent code review (`review/REVIEW_PLAN.md`) found several bugs. Each test here reproduces
one of those bugs so it can't come back unnoticed. See row 10 of `AGENT_LOG.md` for the list.
