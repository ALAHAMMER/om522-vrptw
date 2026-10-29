# `notebooks/`: interactive screens (marimo)

marimo notebooks are plain `.py` files that open in your web browser as interactive pages.

| File | Open it with | What it is for |
|---|---|---|
| `walkthrough.py` | `pixi run walkthrough` | **The screen we record the videos from.** It goes step by step through loading the data, the rule, the checker, the LNS, and the stress test, with a note before each cell. Its buttons run the real commands on a fresh copy of an instance. |
| `explore.py` | `pixi run explore` | Optional playground: pick an instance, run both methods, and look at maps and vehicle timelines. |

The `__marimo__/` folder that marimo creates here is a cache. Git ignores it.
