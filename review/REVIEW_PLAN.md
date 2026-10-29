# Review findings and proposed adjustment plan

Reviewed: 2026-10-15. Scope: CLAUDE.md, knowledge/01 through 07, the deliverable README and agent log, source modules, scripts, tests, Pixi configuration, marimo notebook, and saved results. The knowledge/reference_code folder is explicitly superseded by src/vrptw; this review concentrates on the deliverable implementation. Original course PDFs and published papers were not independently audited.

No solver, notebook, test, dependency, supplied input, or existing result files were changed. The review adds this document and the separate review/verify_findings.py reproduction script.

## Validation and overall assessment

- Existing suite: 16 tests passed in 2.47 seconds earlier in this review.
- Existing marimo check: passed with exit status 0.
- Review-only counterexamples: run using `pixi run python ../review/verify_findings.py` from om522-vrptw.
- Data handling already uses Polars. Solver hot loops appropriately use integer-indexed Python lists and cached route state. The exploratory notebook is a marimo .py file and delegates solver logic to modules.
- The independent checker imports no solver implementation. Departure, waiting, service-start windows, return legs, and vehicle capacity are implemented consistently on the supplied examples.
- Passing the existing tests does not cover the failures below. The synthetic non-metric example is intentionally stronger than the small triangle-inequality violations reported in the supplied data; it establishes a logic defect, not that the saved submitted decisions are infeasible.

## Findings, in priority order

### R1 — High: repair can declare an infeasible plan successful

Location: om522-vrptw/src/vrptw/lns.py:91, :389, :396–410.

Removing stops can make a remaining route infeasible when travel times are non-metric. The ruin loop refreshes caches but does not validate the shortened routes. insertion_cost checks the new stop and its suffix; it assumes the existing prefix is feasible. Therefore inserting a stop elsewhere does not repair an already-late earlier stop. regret_insertion can return True, local search can leave the violation intact, and the acceptance code compares travel without checking full feasibility.

Reproduced with a symmetric four-customer matrix: the starting plan [[1,2,4],[3]] is feasible and costs 204; after removing customers 1 and 4, repair returns True for [[2],[1,3,4]], cost 43. Local search leaves that plan unchanged, although customer 2 is late.

Impact: an invalid trial can become the best incumbent. The CLI's final validation prevents export, but then exits with an internal error instead of returning an earlier feasible plan. Notebook and comparison callers lack that same final protection.

Proposed fix: define a safe policy for infeasible shortened routes, and validate repaired routes before local search/acceptance. Retain a known feasible incumbent throughout. A simple first fix can discard an invalid ruined trial; more ambitious repair can follow later if needed.

### R2 — High: unsuccessful runs leave stale successful outputs

Location: om522-vrptw/src/vrptw/cli.py:35–66.

Reproduced by solving hand_checkable into one directory, then solving edge_case into that same directory. Both exit 0; the second prints no feasible decision found, but the old decision.json and summary.json remain. The malformed-input branch also returns without invalidating old outputs.

Impact: users or grading automation can mistake a previous solution for the current run.

Proposed fix: safely manage the two tool-owned output files for every run. Validate input/output location choices before cleanup, preserve unrelated files, and publish successful files atomically. Add reused-directory tests for both malformed and infeasible runs.

### R3 — Medium: the safety time cap does not cover expensive inner work

Location: om522-vrptw/src/vrptw/lns.py:329, :379, :419–436; cli.py:75–81.

The deadline is checked at the beginning of ruin iterations, but construction, initial VND, regret insertion, and VND inside an iteration have no deadline checks. With time_cap=0 the solver still constructs and improves a solution before observing the deadline. The small reproduction took about 0.0033 seconds; it demonstrates scope, not a default-budget timeout.

Impact: on a difficult instance, the nominal 480-second cap cannot guarantee the whole command stays below 600 seconds. CLI runtime also excludes input loading and output writing; summary.json does not record the configured cap when the run completes normally.

Proposed fix: pass a shared deadline through expensive phases, check at safe intervals, return the best feasible plan on interruption, and report configured cap, actual iterations, stop reason, solver time, and whole-command elapsed time. Keep iteration counts as the normal stopping rule.

### R4 — Medium: integer overflow escapes the input-error contract

Location: om522-vrptw/src/vrptw/instance.py:83–94.

All numeric text passes through Float64 before integer conversion. A capacity of 9223372036854775808 raises an uncaught Polars InvalidOperationError rather than the intended InputError naming the file and column. Float64 also cannot preserve all integer values beyond 2^53.

Proposed fix: explicitly validate supported integer range and convert without silently losing integer precision, while preserving the documented acceptance of integral decimal text such as 60.0. Translate conversion failures into InputError. Add boundary and overflow tests.

### R5 — Medium: comparison reports do not enforce checker success

Location: om522-vrptw/scripts/compare.py:96–108; scripts/gurobi_benchmark.py:143–154.

The comparison writes a decision, runs the checker, records feasible=False if necessary, then continues to build tables and stress results. A None solution also reaches build_decision without handling. The benchmark similarly writes checked plans without rejecting failed checks.

Proposed fix: handle no-solution results explicitly and stop with a useful diagnostic before publishing final reports when a purported solution fails validation. Generate into a temporary results area so a failed regeneration does not leave a mixture of old and new artifacts.

### R6 — Medium: benchmark arc pruning assumes a metric property the data do not guarantee

Location: om522-vrptw/scripts/gurobi_benchmark.py:63–66; knowledge/03-routing-theory.md:41; knowledge/02-option3-data-and-rule.md, edge-case advice.

The benchmark treats S + T[0][i] as a lower bound on arrival at customer i. With a non-metric table, traveling via another customer can arrive earlier, even after service. Example: T[0,A]=1, service[A]=1, T[A,B]=1 gives arrival B=3 even when T[0,B]=10. Using 10 can incorrectly prune a feasible B-to-next-customer arc.

For the same reason, the knowledge files' blanket claim that every customer must have a feasible singleton route is unsafe on general non-metric tables. Capacity-only impossibility checks remain sound.

Impact: pruning may exclude a better feasible solution, making an optimality proof apply only to the restricted model. This review has not demonstrated that the saved optimality results for the supplied instances are wrong.

Proposed fix: use a proven lower bound, such as shortest-path travel lower bounds, or remove that pruning. Revalidate the optional benchmark before repeating its optimality claims. Correct the singleton guidance before implementing any suggested pre-check.

### R7 — Medium: asymmetric 2-opt skips genuine improvements

Location: om522-vrptw/src/vrptw/lns.py:181–199.

The true-cost confirmation prevents accepting a worsening reversal, but it runs only after a symmetric-only boundary delta is negative. On asymmetric data, a reversal can improve its internal arcs even if that boundary delta is zero or positive.

Reproduced: route [1,2,3] costs 8; feasible reversal [3,2,1] costs 4; _two_opt returns False.

Proposed fix: retain the fast boundary delta for verified symmetric matrices and use a correct directed reversal delta otherwise. This is a solution-quality issue, not evidence of an invalid saved route on the symmetric supplied instances.

### R8 — Medium: the benchmark gap description is ambiguous

Location: om522-vrptw/scripts/gurobi_benchmark.py:154, :171–172; README.md, optimality table.

The reported 26.8% uses (incumbent - lower_bound) / incumbent. This correctly bounds the fraction of the incumbent cost that could be saved. It is not the usual statement that the incumbent is at most 26.8% above the optimum, whose denominator would be the optimum. Using the displayed lower bound gives an upper bound of approximately 36.6% for that latter measure.

Proposed fix: label the existing quantity as incumbent-relative gap or maximum reducible share, or additionally report the lower-bound-relative gap with its formula. Clarify what is proven only after addressing R6.

## Documentation and lower-priority improvements

1. README's uniform slowdown thresholds (16% and 26%) and five 60-customer proxy claims lack regeneration code in compare.py. Save the experiment definitions and outputs or narrow the claim that one command regenerates every reported result.
2. knowledge/04-algorithms-playbook.md still recommends 2000 iterations and the old temperature formula in its tuning section, despite documenting the new defaults elsewhere. Its statement that any improving move guarantees more than 0.001 improvement is also false: move acceptance uses 1e-8. Require the final measured improvement explicitly.
3. The marimo timeline text measures slack from service completion, but the constrained event is service start. Explain window slack as window_end - service_start; downstream slack also depends on subsequent stops and shift end.
4. Notebook comparison values are rounded before building the Polars table. Keep raw values in the frame and format only the display if rounded presentation is allowed. decision.json already preserves full precision. Distinguish presentation rounding from actual feasibility calculations.
5. CLI arguments accept nonsensical budgets such as negative iteration or restart counts and non-finite caps. Add argparse validation and make summaries reflect actual settings.
6. load_scenarios uses np.empty without checking complete, unique, contiguous scenario/arc coverage. Generated files satisfy this today, but missing rows in a reused file can leave uninitialized factors. Validate saved scenario files before replay.
7. The heterogeneous-fleet test permits both methods to return None and still pass. Add an explicitly feasible small mixed-fleet fixture with an asserted solution.
8. No broad performance rewrite is justified yet. Candidate opportunities: profile per-iteration reconstruction of every Route, cache route prefix loads rather than rebuilding them for each 2-opt* pair, and avoid repeatedly loading identical instance CSVs in independent checks where a separate parsed checker representation can be reused safely. Measure end-to-end benefit and preserve checker independence.
9. Keep Polars, plain Python hot loops, Pixi, and marimo .py notebooks. Eager CSV reads are reasonable for these sizes. Adding pandas, multiprocessing, or Numba is unnecessary without profiling evidence.
10. Confirm the team has actually performed the review described by the README's attribution paragraph, and replace its team-authored introduction placeholder before submission.

## Proposed adjustment plan — no implementation changes yet

1. **Protect correctness first.** Add focused regression cases for R1 and R2, then fix repaired-plan acceptance and stale outputs. Require all accepted incumbents to be feasible and ensure a failed run cannot expose a previous run's decision.
2. **Harden command behavior.** Fix integer boundary handling, validate CLI options, apply a shared deadline, and record complete run metadata. Add targeted tests for interruption and malformed copied inputs.
3. **Make reports trustworthy.** Make compare/benchmark reject invalid decisions, fix or remove unsafe benchmark pruning, label gap percentages precisely, validate scenario coverage, and make reported sensitivity experiments reproducible.
4. **Improve search where justified.** Fix directed 2-opt if asymmetric inputs are in scope. Profile default 45-, 60-, and 120-customer runs before choosing any caching changes. Compare travel, runtime, and determinism before and after.
5. **Finish the marimo and documentation pass.** Keep raw comparison values, correct the timeline explanation, reconcile guidance/defaults, and update team attribution and limitations.
6. **Validate the final candidate once.** Run the required tests plus the new regression cases, marimo check, independent checks on all four development instances, repeated default-seed solves, mixed-fleet and asymmetric/non-metric fixtures, and a reproducible 60-customer proxy. Regenerate final results only after correctness checks pass.

Acceptance criteria: the worked example remains exact; malformed and infeasible runs follow the required exit/output contract; no infeasible trial replaces a feasible incumbent; default runs remain repeatable unless a documented safety cap intervenes; both methods face the same saved stress scenarios; and any benchmark proof describes the unrestricted valid model.

