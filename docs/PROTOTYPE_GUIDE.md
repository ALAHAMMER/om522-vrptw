# Your short prototype presentation

**Use the existing rule + LNS. Aim for about 8:45, with about 1:15 spare.** The route-pool experiment belongs in later research, not this recording. It saves some travel on large but is harder to explain and performed worse in the latest traffic sensitivity test.

For a short explanation of what Codex added to Claude's project, use [CODEX_CHANGES.md](CODEX_CHANGES.md). It includes an optional 25-second statement; do not add a long change-history section to the recording.

The slide deck is `presentation/Prototype_Simple.pptx` (PDF copy beside it), and `presentation/Prototype_Speaker_Notes.docx` has every slide's notes for printing. Start with `presentation/START_HERE.md`. The deck's speaker notes contain a short script and on-screen instructions. Replace A, B, and C with your names. Rephrase the draft in words you understand; each member must personally run their assigned check before claiming the team verified it.

## Three pieces of code, three people

| Person | Their small component | What it does | What was wrong or unclear | How to show it was checked |
|---|---|---|---|---|
| A | Input reader, `src/vrptw/instance.py` | Reads the CSVs and rejects bad input | The agent log records that guessing types hid useful error messages | Delete `window_end` from a copied file; the message names `customers.csv` and the missing column |
| B | Next-stop choice, `src/vrptw/rule.py` | Picks the nearest stop that fits capacity, window, and return time | “Nearest” must mean travel time, not arrival time including waiting | Rule reproduces the instructor's worked example: 352.417 minutes and the same visits |
| C | Route checker, `src/vrptw/checker.py` | Recalculates times from visits and input files | It must not trust the solver's reported arrival times | Reverse a route and drop C006: the checker rejects it |

These are documented agent-draft issues in `AGENT_LOG.md`; do not imply you personally discovered historical errors if you did not. The rehearsal command reproduces the checks now. Each code slide shows three real source lines, each followed by an orange plain-English line: point at the code and read the orange line, then explain the component's purpose.

## The algorithm in 30 seconds

“The rule fills one truck at a time with the nearest feasible customer. Our researched method builds starting routes, makes small feasible improvements, then repeatedly removes a few customers and inserts them again in better positions. It sometimes accepts a worse draft to escape a dead end, but it keeps the best feasible plan. We use seed 522 and 8,000 attempts, with a 480-second safety cap. It is a heuristic, so it does not guarantee the best possible answer on every new case.”

Regret insertion just means prioritizing customers with few good placement alternatives. A route is an ordered list of customers assigned to one vehicle. No annealing equation or integer-programming model is needed in this prototype explanation.

## Ten slides: about 8:45

| Slide | Who | Time | Show |
|---|---|---:|---|
| 1. Title | A | 0:10 | Names; a real route map from the tool |
| 2. The decision we automate | A | 0:35 | Who uses the tool, the three requirements, what “good” means |
| 3. Reject bad files before planning | A | 1:05 | Three input-reader lines in plain English; issue + check |
| 4. The rule | B | 1:10 | Three next-stop lines in plain English; issue + worked-example check |
| 5. Researched method | B | 1:00 | Four plain-language steps; seed, stopping rule, source, limitation |
| 6. Check every plan independently | C | 1:05 | Three timing lines in plain English; issue + broken-plan check |
| 7. Live demo | A then C | 1:45 | Fresh copy, both methods, checker, outputs, rehearsal checks |
| 8. Same 45 customers, two plans | B | 0:30 | Rule vs LNS route maps; travel and trucks saved |
| 9. All four supplied cases | B | 0:40 | Travel, trucks, runtime table; percent saved chart |
| 10. Next: slower traffic | C | 0:45 | Uncertain input = travel times; stress-test plan; limitation |

Leave most of the screen on the terminal during slide 7. Do not read JSON line by line. Point to the new input path, `feasible: true`, `customers_served: 45`, and the output directory. Open one real `decision.json` if time permits; the console also previews an actual route.

## Rehearse and record

From `om522-vrptw/`:

```powershell
pixi install --locked
pixi run prototype-demo --checks-only
pixi run prototype-demo
```

During slide 7, run the last two commands in the opposite order: `prototype-demo` first, then `prototype-demo --checks-only`. The first creates a new copied medium instance on every run, invokes the original solver CLI for both methods, invokes the independent checker, previews the actual exported routes, and rechecks the four-case saved comparison. The second demonstrates the malformed copy, both edge-case responses, the worked example, the broken-plan rejection, and the 37 project tests. Keep the terminal font large.

The live solve may take 10–30 seconds or more under load. Talk through the four-step algorithm while it runs. The comparison slide uses saved run timings, explicitly labeled; the live summary shows the current runtime. Do not say the current run took nine seconds unless it actually did.

The independent comparison also remains reproducible with the existing `pixi run compare`. Run that before freezing your final submission version, rather than spend the recording regenerating all scenarios and plots.

**Environment check:** both `pixi run prototype-demo` and `pixi run prototype-demo --checks-only` ran successfully through Pixi in a normal Windows terminal on October 29, 2026. The full demo took about 10 seconds and the checks about 8 seconds, with 37 tests passed. A clean `pixi install` from a fresh GitHub clone also worked. Each presenter should still run the commands once on the computer used for recording.

## What the instructor actually requires

Checked against the original `team-project-guide.pdf`, page 5, prototype deliverables and rubric; common method/checking requirements are on pages 2–3. The option-3 brief defines the actual routing constraints.

- At most 10 minutes; every member speaks and explains one agent-drafted component: what it does, an error/unclear point, and how checked.
- A fresh supplied input copied to a new path, both methods running, both actual decisions checked, and initial comparison on at least three common cases.
- Travel is primary; vehicles and runtime also reported. Service starts inside windows, every customer served once, capacity respected, vehicles return within shifts.
- Four input checks and three required tests are implemented and demonstrated in rehearsal.
- Explain the decision in your own words and name the uncertain input for the final. Full stress results are final-stage work, not required in this prototype video.
- Submit the repository URL, the exact commit hash shown, and an unlisted YouTube link viewable without an access request. The instructor stops at the time limit.

Before submitting, rewrite the README opening yourselves, verify the AI-review attribution, push the version shown, record its commit hash, test the video link, and complete the required individual peer evaluation. These are team actions; they have not been performed by the agent.

Save local demo output for rehearsal evidence, but exclude `out/`, `.pixi/`, caches, credentials, and machine-specific paths from the repository upload. Use different components for each member's later final video.

## Keep the presentation small

Save Gurobi optimality, route pools, traffic distributions, cost sliders, crossing analysis, detailed neighborhood formulas, and all five local-search functions for questions or the final. They are not needed to satisfy this prototype. Do not claim the heuristic always finds the global optimum, that the 60-customer proxies are the instructor's held-out case, or that passing tests proves no bugs exist.
