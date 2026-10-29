# What Codex changed from the Claude-generated project

**The original routing solver remains the prototype's solver.** Codex added independent evaluation, separate algorithm experiments, a simpler demonstration, and presentation materials. It did not replace Claude's routing code.

“Original” here means the project as it existed when this review began. Some problems in early Claude drafts had already been fixed. Those historical fixes are recorded in `AGENT_LOG.md`; they are not new Codex changes.

## Short explanation for the presentation

> Claude drafted the original routing tool. Codex independently reviewed it, tested alternative methods, and simplified our demonstration. One alternative saved more travel but caused more lateness in simulated traffic, so we kept the existing solver for the prototype. We also added a fresh-input demo and divided the explanation into three small components.

This is optional background, about 25 seconds. It does **not** replace each teammate's required explanation of their component, its error or unclear point, and how it was checked. Explain only what you understand and have personally reviewed.

## Actual changes

| Area | What was added or changed | Why |
|---|---|---|
| Demonstration | Added `scripts/prototype_demo.py` and the `prototype-demo` Pixi task | Run both existing methods on a fresh copied input, check their actual decisions, preview outputs, and show the comparison without scrolling through a long notebook |
| Rehearsal checks | Added `prototype-demo --checks-only` | Demonstrate missing-column and bad-type rejection, both edge-case responses, the worked example, a deliberately broken plan, and the existing tests |
| Presentation | Added the first simple deck and speaker notes (since redesigned as the 10-slide deck in `presentation/`), plus the prototype guide in `docs/` | Give three beginners small, explainable components and an 8:30 recording target |
| Documentation | Added a README link to the new guide, this change note, review reports, and a separate Codex section in the agent log | Make attribution, requirements, and remaining team actions clear |
| Algorithm experiments | Ran separate block-removal and route-pool experiments, kept outside this repository | Test potential improvements without changing the graded solver or its dependencies |
| Evaluation | Added construction/budget/seed comparisons and new paired traffic simulations | Distinguish travel savings from repeatability, computation cost, and reliability |
| Recommendation | Kept current LNS as the prototype choice after traffic testing | The shorter experimental plans were less reliable under the tested traffic model |

## What did not change

- The existing rule, LNS, input loader, independent checker, decision writer, and solver CLI source modules.
- Default seed 522, 8,000 LNS iterations, and the 480-second safety cap.
- Instructor-supplied inputs, the worked example, and original submitted result files.
- The project's package dependencies, lockfile, and 37 original automated tests.
- The primary objective: total travel time. Reliability remains an additional evaluation, not a silently substituted grading objective.

The Pixi **task list** changed; package dependencies did not. The experimental route-pool worker used a separate existing SciPy interpreter, which is not required by the prototype.

## Why the experimental algorithm was not adopted

The experiment code and its outputs are not part of this repository, so the numbers below cannot be regenerated from it. They are reported only to explain why the existing solver was kept. On the supplied 120-customer case, route-pool recombination improved nominal travel from **2,135.606 to 2,112.408 minutes**, with the same 19 trucks. The mixed two-search configuration took about 64 seconds rather than about 28 seconds for the current LNS.

However, on 1,000 paired base-traffic simulations, the original LNS had **771 fully on-time days**, compared with **746** for the hybrid. Average late events increased from **0.686 to 0.872 per day**. Thus, the experiment improved the graded travel measure on that case but did not establish a better operational plan. These are results within an assumed traffic model, not observed real delivery days.

The medium and new 60-customer comparisons tied the current solver. The practical decision was to keep the established method, retain the experiments as evidence, and avoid adding complexity to a beginner prototype presentation.

## What was verified, and what remains

The fresh-input demonstration, negative checks, and all **37 project tests** passed using the installed project interpreter. The route-pool experiment also had three separate model checks, giving 40 tests when those review-only checks were included. The prototype correctly reports 37 project tests.

The original solver/input/plan files were compared with the earlier SHA256 manifest and remained unchanged. The original course PDFs were read directly when preparing the prototype checklist.

Pixi crashed inside Codex's sandbox, so Codex could not run these through Pixi itself. Afterwards, on October 29, 2026, both `prototype-demo` modes and `pixi run test` ran successfully through Pixi in a normal Windows terminal, and a clean `pixi install` from a fresh GitHub clone worked. Each member must still rehearse their component; the team must write its own README opening, confirm attribution, record the video, and submit the repository, recorded commit hash, and accessible video link.

For the recording, use [PROTOTYPE_GUIDE.md](PROTOTYPE_GUIDE.md).
