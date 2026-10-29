"""Stress test of fixed plans under uncertain travel times (project guide section 2.7).

Uncertain input: travel times. Scenario s multiplies the travel time of arc (i, j) by
    factor[s, i, j] = day[s] * arc[s, i, j]
where day[s] is a congestion factor shared by every road that day (lognormal, mean 1, CV 0.2) and
arc[s, i, j] is road-specific noise (lognormal, mean 1, CV 0.1, made symmetric so i->j equals j->i).
The 30 scenarios are generated from a documented seed and saved to Parquet BEFORE any plan is
executed, so both methods face identical realizations.

Execution rule (option 3 brief): follow each planned route in order without changing any decision.
Every service that starts after its window end and every late return counts as a violation.
"""

from pathlib import Path

import numpy as np
import polars as pl

from vrptw.instance import TOL, Instance

N_SCENARIOS = 30
SCENARIO_SEED = 20261008
DAY_CV = 0.2
ARC_CV = 0.1


def _lognormal_mean_one(rng: np.random.Generator, cv: float, size) -> np.ndarray:
    sigma = np.sqrt(np.log(1.0 + cv**2))
    return rng.lognormal(mean=-(sigma**2) / 2.0, sigma=sigma, size=size)


def generate_scenarios(inst: Instance, path: Path, n_scenarios: int = N_SCENARIOS,
                       seed: int = SCENARIO_SEED, day_cv: float = DAY_CV, arc_cv: float = ARC_CV,
                       day_mean: float = 1.0) -> Path:
    """Write the scenario factors in long format: scenario, day_factor, from_id, to_id, factor."""
    rng = np.random.default_rng(seed)
    size = len(inst.ids)
    day = day_mean * _lognormal_mean_one(rng, day_cv, n_scenarios)
    arc = _lognormal_mean_one(rng, arc_cv, (n_scenarios, size, size))
    # Symmetric road noise: keep the upper triangle and mirror it, so i->j equals j->i while each
    # road keeps exactly the lognormal(mean 1, CV arc_cv) distribution.
    upper = np.triu(arc)
    arc = upper + np.triu(arc, 1).transpose(0, 2, 1)
    factor = day[:, None, None] * arc
    s, i, j = np.indices(factor.shape)
    ids = np.asarray(inst.ids)
    frame = pl.DataFrame({
        "scenario": s.ravel().astype(np.int32),
        "day_factor": day[s.ravel()],
        "from_id": ids[i.ravel()],
        "to_id": ids[j.ravel()],
        "factor": factor.ravel(),
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(path)
    return path


def load_scenarios(inst: Instance, path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Read saved scenarios back into an array factor[s, i, j] using this instance's node order."""
    frame = pl.read_parquet(path)
    index = {node: k for k, node in enumerate(inst.ids)}
    n_s = frame.get_column("scenario").n_unique()
    # The array below starts uninitialised, so the file must cover every scenario and arc exactly once.
    size = len(inst.ids)
    if sorted(frame.get_column("scenario").unique().to_list()) != list(range(n_s)):
        raise ValueError(f"{path}: scenario numbers must run 0..{n_s - 1} without gaps")
    if frame.height != n_s * size * size or frame.select(
            pl.struct("scenario", "from_id", "to_id").is_duplicated().any()).item():
        raise ValueError(f"{path}: every scenario must list each of the {size * size} arcs exactly once")
    factor = np.empty((n_s, len(inst.ids), len(inst.ids)))
    factor[
        frame.get_column("scenario").to_numpy(),
        frame.get_column("from_id").replace_strict(index, return_dtype=pl.Int64).to_numpy(),
        frame.get_column("to_id").replace_strict(index, return_dtype=pl.Int64).to_numpy(),
    ] = frame.get_column("factor").to_numpy()
    day = frame.group_by("scenario").agg(pl.col("day_factor").first()).sort("scenario")
    return factor, day.get_column("day_factor").to_numpy()


def execute_plan(inst: Instance, routes: list[list[int]], factor: np.ndarray) -> dict:
    """Run a fixed plan under one scenario's travel times and count violations."""
    T = (inst.T_np * factor).tolist()
    travel = 0.0
    late_starts = late_returns = 0
    for v, route in enumerate(routes):
        if not route:
            continue
        clock, previous = inst.shift_start[v], 0
        for c in route:
            travel += T[previous][c]
            arrival = clock + T[previous][c]
            start = arrival if arrival > inst.ws[c] else inst.ws[c]
            if start > inst.we[c] + TOL:
                late_starts += 1
            clock, previous = start + inst.service[c], c
        travel += T[previous][0]
        if clock + T[previous][0] > inst.shift_end[v] + TOL:
            late_returns += 1
    return {
        "travel_time": travel,
        "vehicles_used": sum(1 for r in routes if r),
        "late_service_starts": late_starts,
        "late_returns": late_returns,
        "violations": late_starts + late_returns,
    }


def run_stress_test(inst: Instance, plans: dict[str, list[list[int]]], scenario_path: Path) -> pl.DataFrame:
    """One row per (method, scenario)."""
    factor, day = load_scenarios(inst, scenario_path)
    rows = [
        {"method": method, "scenario": s, "day_factor": float(day[s]), **execute_plan(inst, routes, factor[s])}
        for method, routes in plans.items()
        for s in range(factor.shape[0])
    ]
    return pl.DataFrame(rows)


def summarize_stress(results: pl.DataFrame) -> pl.DataFrame:
    return (
        results.group_by("method")
        .agg(
            pl.col("travel_time").mean().alias("travel_mean"),
            pl.col("travel_time").quantile(0.9, interpolation="linear").alias("travel_p90"),
            pl.col("vehicles_used").mean().alias("vehicles_mean"),
            pl.col("vehicles_used").quantile(0.9, interpolation="linear").alias("vehicles_p90"),
            (pl.col("violations") > 0).sum().alias("scenarios_with_violation"),
            pl.col("late_service_starts").sum().alias("late_service_starts_total"),
            pl.col("late_returns").sum().alias("late_returns_total"),
        )
        .sort("method")
    )
