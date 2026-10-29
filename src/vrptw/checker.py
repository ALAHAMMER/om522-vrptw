"""Independent solution checker for option 3.

It reads only the instance CSV files and an exported decision.json, and it recomputes every time
and measure from the visit lists. It deliberately imports nothing from the solver modules (only
the Python standard library), so a bug in a solver cannot hide itself here.

Usage: python -m vrptw.checker <instance_dir> <decision.json>
Exit status 0 if the decision is feasible, 1 otherwise.
"""

import csv
import json
import sys
from pathlib import Path

TOL = 1e-8


def _rows(folder: Path, name: str) -> list[dict]:
    with open(folder / name, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def check_decision(instance_dir: str | Path, decision: dict) -> dict:
    folder = Path(instance_dir)
    customers = {r["customer_id"].strip(): r for r in _rows(folder, "customers.csv")}
    vehicles = {r["vehicle_id"].strip(): r for r in _rows(folder, "vehicles.csv")}
    depot = _rows(folder, "depots.csv")[0]["node_id"].strip()
    travel = {(r["from_id"].strip(), r["to_id"].strip()): float(r["travel_time"])
              for r in _rows(folder, "travel_times.csv")}

    violations: list[str] = []
    warnings: list[str] = []
    visits_count: dict[str, int] = {}
    vehicles_seen: set[str] = set()
    total_travel = waiting = 0.0
    vehicles_used = 0

    for route in decision.get("routes", []):
        vid = route.get("vehicle_id")
        if vid not in vehicles:
            violations.append(f"route uses unknown vehicle {vid}")
            continue
        if vid in vehicles_seen:
            violations.append(f"vehicle {vid} makes more than one route")
        vehicles_seen.add(vid)
        vehicle = vehicles[vid]
        visits = route.get("visits", [])
        if any(c not in customers for c in visits):
            violations.append(f"{vid}: visits unknown customers {[c for c in visits if c not in customers]}")
            continue
        if visits:
            vehicles_used += 1

        clock, previous, load = float(vehicle["shift_start"]), depot, 0
        arrivals, starts = [], []
        for c in visits:
            visits_count[c] = visits_count.get(c, 0) + 1
            customer = customers[c]
            leg = travel[(previous, c)]
            total_travel += leg
            arrival = clock + leg
            start = max(arrival, float(customer["window_start"]))
            waiting += start - arrival
            if start > float(customer["window_end"]) + TOL:
                violations.append(
                    f"{vid}: service at {c} starts at {start:.6f}, after its window end {customer['window_end']}"
                )
            load += int(float(customer["demand"]))
            arrivals.append(arrival)
            starts.append(start)
            clock, previous = start + float(customer["service_time"]), c
        if visits:
            total_travel += travel[(previous, depot)]
            return_time = clock + travel[(previous, depot)]
        else:
            return_time = float(vehicle["shift_start"])
        if return_time > float(vehicle["shift_end"]) + TOL:
            violations.append(f"{vid}: returns at {return_time:.6f}, after shift end {vehicle['shift_end']}")
        if load > int(float(vehicle["capacity"])):
            violations.append(f"{vid}: load {load} exceeds capacity {vehicle['capacity']}")

        # Reported times are not trusted, but a mismatch signals a bug in the writer.
        for label, reported, computed in (("arrivals", route.get("arrivals"), arrivals),
                                          ("service_starts", route.get("service_starts"), starts)):
            if reported is not None and (len(reported) != len(computed) or any(
                    abs(r - c) > 1e-6 for r, c in zip(reported, computed))):
                warnings.append(f"{vid}: reported {label} differ from recomputed values")
        if "return_time" in route and abs(route["return_time"] - return_time) > 1e-6:
            warnings.append(f"{vid}: reported return_time differs from recomputed value")

    unserved = sorted(set(customers) - set(visits_count))
    repeated = sorted(c for c, k in visits_count.items() if k > 1)
    if unserved:
        violations.append(f"customers not served: {unserved}")
    if repeated:
        violations.append(f"customers served more than once: {repeated}")

    return {
        "feasible": not violations,
        "violations": violations,
        "warnings": warnings,
        "total_travel_time": total_travel,
        "vehicles_used": vehicles_used,
        "waiting_time": waiting,
        "customers_served": sum(visits_count.values()),
    }


def check_files(instance_dir: str | Path, decision_path: str | Path) -> dict:
    decision = json.loads(Path(decision_path).read_text(encoding="utf-8"))
    return check_decision(instance_dir, decision)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: python -m vrptw.checker <instance_dir> <decision.json>", file=sys.stderr)
        return 2
    result = check_files(args[0], args[1])
    print(json.dumps(result, indent=2))
    return 0 if result["feasible"] else 1


if __name__ == "__main__":
    sys.exit(main())
