"""Turn routes into the decision.json structure and summary measures, and write them to disk."""

import json
import os
from pathlib import Path

from vrptw.instance import Instance, route_schedule, route_travel


def build_decision(inst: Instance, routes: list[list[int]]) -> dict:
    """decision.json content: one entry per USED vehicle, times at full precision (never rounded)."""
    out = []
    for v, route in enumerate(routes):
        if not route:
            continue
        arrivals, starts, return_time = route_schedule(inst, v, route)
        out.append({
            "vehicle_id": inst.vehicle_ids[v],
            "visits": [inst.ids[c] for c in route],
            "arrivals": arrivals,
            "service_starts": starts,
            "return_time": return_time,
        })
    return {"routes": out}


def measures(inst: Instance, routes: list[list[int]]) -> dict:
    """Primary and secondary measures, the waiting and service consequences the brief asks for,
    and consistency counts, computed from the routes."""
    waiting = duration = 0.0
    for v, route in enumerate(routes):
        if route:
            arrivals, starts, back = route_schedule(inst, v, route)
            waiting += sum(s - a for a, s in zip(arrivals, starts))
            duration += back - inst.shift_start[v]  # depot departure (shift start) to return
    return {
        "total_travel_time": sum(route_travel(inst, r) for r in routes),
        "vehicles_used": sum(1 for r in routes if r),
        "waiting_time": waiting,
        "service_time": sum(inst.service[c] for r in routes for c in r),
        "route_duration": duration,  # travel + waiting + service on every used vehicle
        "customers_served": sum(len(r) for r in routes),
    }


OUTPUT_FILES = ("decision.json", "summary.json")


def _write_atomically(path: Path, text: str) -> None:
    """Write to a temporary file, then rename, so a reader never sees a half-written file."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def write_outputs(output_dir: str | Path, decision: dict, summary: dict) -> None:
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    _write_atomically(folder / "summary.json", json.dumps(summary, indent=2))
    _write_atomically(folder / "decision.json", json.dumps(decision, indent=2))  # last: marks completion
