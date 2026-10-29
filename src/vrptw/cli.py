"""Command-line entry point: pixi run solve <input_dir> <output_dir> [options].

Exit behaviour required by the project guide:
- malformed input: message naming the file and column, no decision.json, exit status 2
- valid input with nothing feasible: prints "no feasible decision found", no decision.json, exit 0
- otherwise: writes decision.json and summary.json, exit 0

Every run first removes decision.json and summary.json left in the output directory by an earlier
run (and nothing else), so a failed or infeasible run can never leave an old decision behind.
"""

import argparse
import json
import math
import platform
import sys
import time
from pathlib import Path

from vrptw.decision import OUTPUT_FILES, build_decision, measures, write_outputs
from vrptw.instance import InputError, load_instance, route_is_feasible
from vrptw.lns import DEFAULT_ITERATIONS, DEFAULT_RESTARTS, DEFAULT_SEED, DEFAULT_TIME_CAP, solve_lns
from vrptw.rule import nearest_feasible_neighbor


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {text}")
    return value


def _non_negative_int(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be zero or more, got {text}")
    return value


def _seconds(text: str) -> float:
    value = float(text)
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError(f"must be a finite number of seconds >= 0, got {text}")
    return value


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="solve", description="Plan delivery routes (OM 522 option 3).")
    parser.add_argument("input_dir", help="instance directory with the option 3 CSV files")
    parser.add_argument("output_dir", help="directory for decision.json and summary.json")
    parser.add_argument("--method", choices=["lns", "rule"], default="lns",
                        help="lns = researched method (default), rule = rule to beat")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--iterations", type=_non_negative_int, default=DEFAULT_ITERATIONS,
                        help="LNS iterations per run")
    parser.add_argument("--restarts", type=_positive_int, default=DEFAULT_RESTARTS, help="independent LNS runs")
    parser.add_argument("--time-cap", type=_seconds, default=DEFAULT_TIME_CAP,
                        help="safety cap in seconds for the LNS (the iteration count is the stopping rule)")
    return parser.parse_args(argv)


def _clear_previous_outputs(input_dir: Path, output_dir: Path) -> str | None:
    """Remove this tool's own files from an earlier run; return an error message if unsafe."""
    if output_dir.exists() and not output_dir.is_dir():
        return f"output path {output_dir} exists and is not a directory"
    if input_dir.exists() and output_dir.resolve() == input_dir.resolve():
        return "the output directory must differ from the input directory (inputs are never modified)"
    for name in OUTPUT_FILES:
        (output_dir / name).unlink(missing_ok=True)
    return None


def main(argv: list[str] | None = None) -> int:
    command_started = time.perf_counter()
    args = parse_args(argv)
    problem = _clear_previous_outputs(Path(args.input_dir), Path(args.output_dir))
    if problem:
        print(f"Output error: {problem}", file=sys.stderr)
        return 2
    try:
        inst = load_instance(args.input_dir)
    except InputError as error:
        print(f"Input error: {error}", file=sys.stderr)
        return 2

    started = time.perf_counter()
    details: dict = {}
    if args.method == "rule":
        routes = nearest_feasible_neighbor(inst)
        details = {"method": "rule to beat (nearest feasible neighbor)"}
    else:
        result = solve_lns(inst, iterations=args.iterations, seed=args.seed,
                           restarts=args.restarts, time_cap=args.time_cap)
        routes = result.routes
        details = {
            "method": "large neighborhood search (researched method)",
            "seed": args.seed,
            "restarts": args.restarts,
            "iterations_per_run": args.iterations,
            "iterations_run_total": result.iterations_run,
            "time_cap_seconds": args.time_cap,
            "stop_reason": result.stop_reason,
            "starting_solution": result.start_method,
            "starting_travel_time": result.start_travel,
        }
    seconds = time.perf_counter() - started

    if routes is None:
        print("no feasible decision found")
        return 0

    # Last line of defence: never export a plan that breaks a constraint.
    broken = [inst.vehicle_ids[v] for v, r in enumerate(routes) if r and not route_is_feasible(inst, v, r)]
    served = sorted(c for r in routes for c in r)
    if broken or served != list(range(1, inst.n + 1)):
        print(f"internal error: solver produced an infeasible plan (vehicles {broken})", file=sys.stderr)
        return 3

    summary = {
        "status": "feasible decision found",
        **details,
        **measures(inst, routes),
        "computation_seconds": seconds,
        "command_seconds_before_writing": time.perf_counter() - command_started,
        "python": platform.python_version(),
        "machine": platform.platform(),
    }
    write_outputs(args.output_dir, build_decision(inst, routes), summary)
    print(json.dumps({k: summary[k] for k in ("status", "method", "total_travel_time",
                                              "vehicles_used", "computation_seconds")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
