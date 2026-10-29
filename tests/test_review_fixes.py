"""Regression tests for the 2026-10-15 review (REVIEW_PLAN.md findings R1-R8 and follow-ups)."""

import math
import random
import shutil
import time
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from vrptw.cli import main as solve_main
from vrptw.crossings import find_crossings
from vrptw.instance import Instance, InputError, load_instance, route_is_feasible, route_travel
from vrptw.lns import Route, _ruin_and_recreate, _two_opt, solve_lns
from vrptw.stress import generate_scenarios, load_scenarios

DATA = Path(__file__).resolve().parents[1] / "data" / "option_03"


def toy_instance(matrix, window_ends=None, vehicles=1, x=None, y=None):
    """Small hand-built instance: unit demand and service, wide windows unless given."""
    n = len(matrix) - 1
    return Instance(
        ids=["DEPOT"] + [f"C{i}" for i in range(1, n + 1)],
        vehicle_ids=[f"V{i}" for i in range(vehicles)],
        demand=[0] + [1] * n, service=[0] + [1] * n, ws=[0] * (n + 1),
        we=window_ends or [math.inf] + [1000] * n,
        cap=[100] * vehicles, shift_start=[0] * vehicles, shift_end=[1000] * vehicles,
        T=matrix, T_np=np.array(matrix, dtype=float),
        x=x or [0] * (n + 1), y=y or [0] * (n + 1),
        symmetric=bool(np.array_equal(np.array(matrix), np.array(matrix).T)),
    )


def nonmetric_instance():
    """The review's counterexample: removing customers 1 and 4 makes customer 2 late."""
    matrix = [[0 if i == j else 20 for j in range(5)] for i in range(5)]
    for a, b, value in [(0, 1, 1), (1, 2, 1), (2, 4, 1), (4, 0, 1), (0, 3, 100),
                        (0, 2, 10), (3, 1, 1), (1, 4, 1)]:
        matrix[a][b] = matrix[b][a] = value
    return toy_instance(matrix, [math.inf, 1000, 5, 1000, 1000], vehicles=2)


# R1: the search never keeps an infeasible plan, even on non-metric travel times.
def test_lns_never_accepts_an_infeasible_plan_on_nonmetric_data():
    inst = nonmetric_instance()
    start = [[1, 2, 4], [3]]
    assert all(route_is_feasible(inst, v, r) for v, r in enumerate(start))
    for seed in range(50):
        plan, cost, _, _ = _ruin_and_recreate(inst, start, sum(route_travel(inst, r) for r in start),
                                              200, random.Random(seed), time.perf_counter() + 30)
        assert all(route_is_feasible(inst, v, r) for v, r in enumerate(plan))
        assert cost == pytest.approx(sum(route_travel(inst, r) for r in plan))


# R2: an infeasible or malformed run never leaves an earlier decision behind.
@pytest.mark.parametrize("second_input", ["edge_case", "malformed"])
def test_failed_run_clears_previous_outputs(tmp_path, capsys, second_input):
    out = tmp_path / "out"
    assert solve_main([str(DATA / "hand_checkable"), str(out), "--method", "rule"]) == 0
    assert (out / "decision.json").exists() and (out / "summary.json").exists()
    source = DATA / "edge_case"
    if second_input == "malformed":
        source = tmp_path / "bad"
        shutil.copytree(DATA / "development_small", source)
        pl.read_csv(source / "vehicles.csv").drop("capacity").write_csv(source / "vehicles.csv")
    solve_main([str(source), str(out)])
    assert not (out / "decision.json").exists()
    assert not (out / "summary.json").exists()


def test_output_directory_must_differ_from_input(tmp_path):
    instance = tmp_path / "instance"
    shutil.copytree(DATA / "hand_checkable", instance)
    assert solve_main([str(instance), str(instance)]) == 2
    assert not (instance / "decision.json").exists()


# R3: the safety cap is honoured inside construction and still yields a feasible plan.
def test_zero_time_cap_returns_a_feasible_plan_quickly():
    inst = load_instance(DATA / "development_medium")
    started = time.perf_counter()
    result = solve_lns(inst, time_cap=0)
    assert time.perf_counter() - started < 2
    assert "time cap" in result.stop_reason
    assert all(route_is_feasible(inst, v, r) for v, r in enumerate(result.routes) if r)
    assert sorted(c for r in result.routes for c in r) == list(range(1, inst.n + 1))


# R4: integer overflow is an input error naming the file and column; integers are never rounded.
@pytest.mark.parametrize(("value", "expected"), [
    ("9223372036854775808", None),          # beyond 64 bits -> input error
    ("9007199254740993.0", None),           # beyond 2^53 with a decimal point -> cannot be exact -> error
    ("9007199254740993", 9007199254740993),  # plain integer text is read exactly, not rounded to 2^53
    ("60.0", 60),                           # integral decimal text is accepted
])
def test_integer_range(tmp_path, value, expected):
    instance = tmp_path / "instance"
    shutil.copytree(DATA / "hand_checkable", instance)
    (pl.read_csv(instance / "vehicles.csv", infer_schema=False)
     .with_columns(pl.lit(value).alias("capacity")).write_csv(instance / "vehicles.csv"))
    if expected is not None:
        assert load_instance(instance).cap[0] == expected
    else:
        with pytest.raises(InputError, match=r"vehicles\.csv: column 'capacity'"):
            load_instance(instance)


# Follow-up 5: nonsense budgets are rejected by the command line.
@pytest.mark.parametrize("option", [["--iterations", "-5"], ["--restarts", "0"], ["--time-cap", "nan"],
                                    ["--time-cap", "-1"]])
def test_cli_rejects_nonsense_settings(tmp_path, option):
    with pytest.raises(SystemExit) as stop:
        solve_main([str(DATA / "hand_checkable"), str(tmp_path / "out"), *option])
    assert stop.value.code == 2


# R7: 2-opt finds improvements on asymmetric travel times.
def test_two_opt_handles_asymmetric_travel_times():
    inst = toy_instance([[0, 1, 10, 1], [1, 0, 5, 10], [10, 1, 0, 1], [1, 10, 1, 0]])
    assert not inst.symmetric
    route = Route(inst, 0, [1, 2, 3])
    assert route.travel == 8
    assert _two_opt(inst, route)
    assert route.travel == 4


def test_supplied_instances_are_flagged_symmetric():
    assert load_instance(DATA / "development_medium").symmetric


# Follow-up 6: a saved scenario file with a missing arc is rejected rather than read as garbage.
def test_incomplete_scenario_file_is_rejected(tmp_path):
    inst = load_instance(DATA / "hand_checkable")
    path = generate_scenarios(inst, tmp_path / "s.parquet", n_scenarios=3)
    load_scenarios(inst, path)  # complete file loads
    pl.read_parquet(path).slice(1).write_parquet(path)
    with pytest.raises(ValueError, match="exactly once"):
        load_scenarios(inst, path)


# Follow-up 7: a mixed fleet with a known feasible answer is solved and respected.
def test_mixed_fleet_is_solved_feasibly(tmp_path):
    instance = tmp_path / "instance"
    shutil.copytree(DATA / "development_small", instance)
    (pl.read_csv(instance / "vehicles.csv")
     .with_columns(pl.Series("capacity", [70, 25, 40, 60, 30, 50, 45]),
                   pl.Series("shift_start", [0, 60, 0, 0, 0, 30, 0]),
                   pl.Series("shift_end", [600, 480, 600, 600, 550, 600, 600]))
     .write_csv(instance / "vehicles.csv"))
    inst = load_instance(instance)
    routes = solve_lns(inst, iterations=300).routes
    assert routes is not None
    assert all(route_is_feasible(inst, v, r) for v, r in enumerate(routes) if r)
    assert sorted(c for r in routes for c in r) == list(range(1, inst.n + 1))


# Crossings: detection works, and no crossing left inside an LNS route can be removed feasibly.
def test_crossing_is_detected_and_uncrossed_when_windows_allow():
    # Square: depot (0,0), customers at (0,1) (1,1) (1,0); visiting 1,3,2 crosses itself.
    xs, ys = [0, 0, 1, 1], [0, 1, 1, 0]
    matrix = [[math.hypot(xs[i] - xs[j], ys[i] - ys[j]) for j in range(4)] for i in range(4)]
    inst = toy_instance(matrix, x=xs, y=ys)
    found = find_crossings(inst, [[1, 3, 2]])
    assert len(found) == 1 and found[0]["kind"] == "same vehicle"
    assert found[0]["uncross_feasible"] and found[0]["uncross_travel_change"] < 0


@pytest.mark.parametrize("name", ["development_small", "development_medium"])
def test_lns_routes_keep_only_unremovable_crossings(name):
    inst = load_instance(DATA / name)
    routes = solve_lns(inst, iterations=500).routes
    for crossing in find_crossings(inst, routes):
        if crossing["kind"] == "same vehicle":
            assert not crossing["uncross_feasible"], crossing
