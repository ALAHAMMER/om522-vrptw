"""Short, real prototype demonstration: pixi run prototype-demo [--checks-only].

The presentation uses the existing rule and LNS CLI, not a simplified replacement solver.
Each invocation creates a fresh directory; supplied data and earlier outputs are preserved.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]       # the om522-vrptw folder
DATA = ROOT / "data" / "option_03"                # the supplied instances (only read, never written)
sys.path.insert(0, str(ROOT / "src"))             # so "import vrptw" finds src/vrptw
from vrptw.checker import check_files


def same_bytes(a: Path, b: Path) -> bool:
    """True if two files have identical contents (compared by their SHA-256 fingerprints)."""
    return hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest()


def call(module, args):
    """Run `python -m <module> <args>` exactly as `pixi run solve` / `pixi run check` would,
    and capture its printed output and exit code."""
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, "-m", module, *map(str, args)], cwd=ROOT,
                          env=env, capture_output=True, text=True, encoding="utf-8", timeout=590)


def comparison():
    """Print the saved comparison (results/comparison.csv), after re-running the independent
    checker on every saved decision rather than trusting its saved feasible flag."""
    frame = pl.read_csv(ROOT / "results" / "comparison.csv")   # one row per (instance, method)
    for row in frame.to_dicts():
        # Re-check the saved decision and confirm the checker's travel time matches the table.
        checked = check_files(DATA / row["instance"], ROOT / "results" / "decisions" /
                              row["instance"] / row["method"] / "decision.json")
        assert checked["feasible"], checked["violations"]
        assert abs(checked["total_travel_time"] - row["total_travel_time"]) < 1e-8
    # Reshape to one row per instance, with rule and LNS columns side by side.
    wide = frame.pivot(on="method", index=["instance", "customers"],
                       values=["total_travel_time", "vehicles_used", "seconds"])
    print("\nCOMPARISON: saved runs, all 8 decisions independently rechecked now.")
    print("Minutes / trucks / measured solve seconds. Display rounded; decision files are full precision.")
    for row in wide.to_dicts():
        print(f"  {row['instance']:20s} "
              f"RULE {row['total_travel_time_rule']:8.3f} / {row['vehicles_used_rule']:2d} / {row['seconds_rule']:.6f}s   "
              f"LNS {row['total_travel_time_lns']:8.3f} / {row['vehicles_used_lns']:2d} / {row['seconds_lns']:.3f}s")
    machine = json.loads((ROOT / "results" / "run_info.json").read_text())["machine"]
    print("  Saved-run computer:", machine)
    print("  LNS: seed 522, 8000 iterations, 480-second safety cap.")
    return frame.to_dicts()


def checks(folder):
    """Rehearsal checks (--checks-only). Each step fails loudly (assert) if the tool misbehaves."""
    # 1. Malformed input: a copy of development_small with the window_end column deleted.
    #    Expect: error naming the file and column, nonzero exit, no decision.json.
    bad = folder / "missing_column"
    shutil.copytree(DATA / "development_small", bad)
    pl.read_csv(bad / "customers.csv").drop("window_end").write_csv(bad / "customers.csv")
    out = folder / "bad_output"
    result = call("vrptw.cli", [bad, out])
    assert result.returncode != 0 and not (out / "decision.json").exists()
    assert "customers.csv" in result.stderr and "window_end" in result.stderr
    print("MALFORMED COPY:", result.stderr.strip())
    print(f"  exit={result.returncode}; decision.json exists=False")

    # 2. Malformed input: every vehicle capacity replaced by the text "sixty" (wrong type).
    bad_type = folder / "bad_type"
    shutil.copytree(DATA / "development_small", bad_type)
    pl.read_csv(bad_type / "vehicles.csv").with_columns(
        pl.lit("sixty").alias("capacity")).write_csv(bad_type / "vehicles.csv")
    out = folder / "bad_type_output"
    result = call("vrptw.cli", [bad_type, out])
    assert result.returncode != 0 and not (out / "decision.json").exists()
    assert "vehicles.csv" in result.stderr and "capacity" in result.stderr
    print("BAD TYPE:", result.stderr.strip())
    print(f"  exit={result.returncode}; decision.json exists=False")

    # 3. Supplied edge case (a demand of 65 exceeds every capacity of 60), with both methods.
    #    Expect: "no feasible decision found", exit 0, no decision.json.
    for method in ("rule", "lns"):
        out = folder / f"edge_{method}"
        result = call("vrptw.cli", [DATA / "edge_case", out, "--method", method])
        assert result.returncode == 0 and "no feasible decision found" in result.stdout
        assert not (out / "decision.json").exists()
        print(f"EDGE CASE ({method}): no feasible decision found; exit=0; decision.json exists=False")

    # 4. Worked example: the rule on hand_checkable must give total travel 352.417.
    result = call("vrptw.cli", [DATA / "hand_checkable", folder / "worked", "--method", "rule"])
    assert result.returncode == 0, result.stderr
    checked = check_files(DATA / "hand_checkable", folder / "worked" / "decision.json")
    assert checked["feasible"] and abs(checked["total_travel_time"] - 352.417) < 1e-8
    print("WORKED EXAMPLE: rule travel=352.417; independent checker passed")

    # 5. Break that plan on purpose (reverse the first route, drop customer C006) and confirm
    #    the checker rejects it with exit code 1 and lists the violations.
    broken =json.loads((folder / "worked" / "decision.json").read_text())
    broken["routes"][0]["visits"].reverse()
    for route in broken["routes"]:
        route["visits"] = [c for c in route["visits"] if c != "C006"]
    path = folder / "deliberately_broken_decision.json"
    path.write_text(json.dumps(broken, indent=2))
    result = call("vrptw.checker", [DATA / "hand_checkable", path])
    caught = json.loads(result.stdout)
    assert result.returncode == 1 and not caught["feasible"]
    assert any("not served" in v for v in caught["violations"])
    print("BROKEN PLAN: checker rejects a reversed route and dropped C006:")
    for violation in caught["violations"]:
        print(" ", violation)

    # 6. The project's full automated test suite (same tests as `pixi run test`).
    result = call("pytest", ["-q", "tests", "-p", "no:cacheprovider", "--basetemp", folder / "pytest_tmp"])
    print("TESTS:", result.stdout.strip())
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    (folder / "checks_passed.json").write_text(json.dumps(dict(
        malformed_rejected=True, bad_type_rejected=True, edge_both_methods=True, worked_example=True,
        broken_plan_rejected=True, test_output=result.stdout), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checks-only", action="store_true", help="run rehearsal safety checks and required tests")
    args = parser.parse_args()
    started = time.perf_counter()
    # Every run gets its own new folder, out/prototype_demo/run_xxxxxxxx/ (git ignores out/).
    parent = ROOT / "out" / "prototype_demo"
    parent.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="run_", dir=parent))
    if args.checks_only:
        checks(folder)
    else:
        # The "fresh instance" the guide asks for: copy the supplied medium instance to a new path,
        # then confirm every copied file is byte-for-byte identical to the original.
        source = DATA / "development_medium"
        fresh = folder / "fresh_medium"
        shutil.copytree(source, fresh)
        for original in source.iterdir():
            if original.is_file():
                assert same_bytes(original, fresh / original.name), f"copy differs: {original.name}"
        print("FRESH INPUT:", fresh.relative_to(ROOT), flush=True)
        print("Copied supplied medium instance; input contents unchanged; 45 customers.", flush=True)
        # Solve the fresh copy with each method, then check each decision independently.
        evidence = []
        for method in ("rule", "lns"):
            out = folder / method
            print(f"\nRUN {method.upper()}: existing solver CLI", flush=True)
            result = call("vrptw.cli", [fresh, out, "--method", method])
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            print(result.stdout.strip(), flush=True)
            summary = json.loads((out / "summary.json").read_text())
            if method == "lns":
                print("  seed:", summary["seed"], "|", summary["stop_reason"],
                      "| safety cap:", summary["time_cap_seconds"], "seconds", flush=True)
            result = call("vrptw.checker", [fresh, out / "decision.json"])
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            checked = json.loads(result.stdout)
            print("INDEPENDENT CHECK:", json.dumps({k: checked[k] for k in (
                "feasible", "violations", "total_travel_time", "vehicles_used", "customers_served")}), flush=True)
            decision = json.loads((out / "decision.json").read_text())
            first = decision["routes"][0]
            print("  Real output preview:", first["vehicle_id"], first["visits"], "return:", first["return_time"])
            print("  Full decision + summary:", out.relative_to(ROOT))
            evidence.append(dict(method=method, summary=summary, checker=checked))
        # Show the saved four-instance comparison, then save everything printed as evidence.
        saved = comparison()
        (folder / "demo_evidence.json").write_text(json.dumps(dict(
            fresh_input=str(fresh.relative_to(ROOT)), live_runs=evidence, saved_comparison=saved), indent=2))
    print(f"\nFinished in {time.perf_counter()-started:.2f}s. Evidence: {folder.relative_to(ROOT)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
