"""The three tests required by the project guide (section 2.5), plus extra safety checks."""

import json
import shutil
from pathlib import Path

import polars as pl
import pytest

from vrptw.checker import check_decision, check_files
from vrptw.cli import main as solve_main
from vrptw.decision import build_decision, measures
from vrptw.instance import InputError, load_instance
from vrptw.lns import solve_lns
from vrptw.rule import nearest_feasible_neighbor

DATA = Path(__file__).resolve().parents[1] / "data" / "option_03"
DEV = ["hand_checkable", "development_small", "development_medium"]


# ----------------------------------------------------------------------------- required test 1
def test_rule_reproduces_worked_example(tmp_path):
    assert solve_main([str(DATA / "hand_checkable"), str(tmp_path), "--method", "rule"]) == 0
    ours = json.loads((tmp_path / "decision.json").read_text())
    expected = json.loads((DATA / "worked-example" / "solution.json").read_text())
    metrics = json.loads((DATA / "worked-example" / "metrics.json").read_text())

    assert [r["vehicle_id"] for r in ours["routes"]] == [r["vehicle_id"] for r in expected["routes"]]
    for mine, theirs in zip(ours["routes"], expected["routes"]):
        assert mine["visits"] == theirs["visits"]
        assert mine["arrivals"] == pytest.approx(theirs["arrivals"], abs=1e-3)
        assert mine["service_starts"] == pytest.approx(theirs["service_starts"], abs=1e-3)
        assert mine["return_time"] == pytest.approx(theirs["return_time"], abs=1e-3)

    checked = check_files(DATA / "hand_checkable", tmp_path / "decision.json")
    assert checked["feasible"]
    assert checked["total_travel_time"] == pytest.approx(metrics["total_travel_time"], abs=1e-3)
    assert checked["vehicles_used"] == metrics["vehicles_used"]
    assert checked["waiting_time"] == pytest.approx(metrics["waiting_time"], abs=1e-3)
    assert checked["customers_served"] == metrics["customers_served"]


def test_route_duration_is_travel_plus_waiting_plus_service():
    """The waiting and service consequences in summary.json add up, on the worked example."""
    inst = load_instance(DATA / "hand_checkable")
    m = measures(inst, nearest_feasible_neighbor(inst))
    assert m["route_duration"] == pytest.approx(m["total_travel_time"] + m["waiting_time"] + m["service_time"])
    # Both worked-example vehicles leave at minute 0, so duration = the sum of their return times.
    assert m["route_duration"] == pytest.approx(361.875 + 289.403, abs=1e-3)


# ----------------------------------------------------------------------------- required test 2
@pytest.mark.parametrize("method", ["rule", "lns"])
def test_edge_case_reports_no_feasible_decision(tmp_path, capsys, method):
    status = solve_main([str(DATA / "edge_case"), str(tmp_path / "out"), "--method", method])
    assert status == 0
    assert "no feasible decision found" in capsys.readouterr().out
    assert not (tmp_path / "out" / "decision.json").exists()


# ----------------------------------------------------------------------------- required test 3
def test_missing_required_column_is_rejected(tmp_path, capsys):
    instance = tmp_path / "instance"
    shutil.copytree(DATA / "development_small", instance)
    pl.read_csv(instance / "customers.csv").drop("window_end").write_csv(instance / "customers.csv")

    status = solve_main([str(instance), str(tmp_path / "out")])
    assert status != 0
    message = capsys.readouterr().err
    assert "customers.csv" in message and "window_end" in message
    assert not (tmp_path / "out" / "decision.json").exists()


# ----------------------------------------------------------------------------- extra checks
@pytest.mark.parametrize(
    ("file", "edit", "words"),
    [
        ("vehicles.csv", lambda df: df.with_columns(pl.lit("sixty").alias("capacity")), ["vehicles.csv", "capacity"]),
        ("customers.csv", lambda df: df.with_columns(pl.lit(0).alias("service_time")), ["customers.csv", "service_time"]),
        ("customers.csv", lambda df: df.with_columns(pl.lit(None).cast(pl.Int64).alias("demand")), ["customers.csv", "demand"]),
        ("travel_times.csv", lambda df: df.with_columns(pl.col("to_id").str.replace("C001", "C999")), ["travel_times.csv", "to_id"]),
        ("travel_times.csv", lambda df: df.slice(1), ["travel_times.csv"]),
    ],
)
def test_other_malformed_inputs_are_rejected(tmp_path, file, edit, words):
    instance = tmp_path / "instance"
    shutil.copytree(DATA / "development_small", instance)
    edit(pl.read_csv(instance / file)).write_csv(instance / file)
    with pytest.raises(InputError) as error:
        load_instance(instance)
    for word in words:
        assert word in str(error.value)


@pytest.mark.parametrize("name", DEV)
def test_lns_is_feasible_and_beats_rule(name):
    inst = load_instance(DATA / name)
    rule_check = check_decision(DATA / name, build_decision(inst, nearest_feasible_neighbor(inst)))
    result = solve_lns(inst, iterations=200, restarts=1)
    lns_check = check_decision(DATA / name, build_decision(inst, result.routes))
    assert rule_check["feasible"] and lns_check["feasible"]
    assert lns_check["total_travel_time"] < rule_check["total_travel_time"] - 0.001
    assert lns_check["total_travel_time"] == pytest.approx(result.travel, abs=1e-6)


def test_lns_is_deterministic():
    inst = load_instance(DATA / "development_small")
    assert solve_lns(inst, iterations=100, seed=7, restarts=2).routes == solve_lns(inst, iterations=100, seed=7, restarts=2).routes


def test_shuffled_rows_give_the_same_decision(tmp_path):
    instance = tmp_path / "instance"
    shutil.copytree(DATA / "development_small", instance)
    for file in ("customers.csv", "vehicles.csv", "travel_times.csv"):
        pl.read_csv(instance / file).sample(fraction=1.0, shuffle=True, seed=1).write_csv(instance / file)
    original = load_instance(DATA / "development_small")
    shuffled = load_instance(instance)
    assert build_decision(original, solve_lns(original, iterations=100, restarts=1).routes) == build_decision(
        shuffled, solve_lns(shuffled, iterations=100, restarts=1).routes
    )


def test_heterogeneous_fleet_is_respected(tmp_path):
    instance = tmp_path / "instance"
    shutil.copytree(DATA / "development_small", instance)
    vehicles = pl.read_csv(instance / "vehicles.csv").with_columns(
        pl.Series("capacity", [70, 25, 40, 60, 30, 50, 45]),
        pl.Series("shift_start", [0, 60, 0, 120, 0, 30, 0]),
        pl.Series("shift_end", [600, 480, 400, 600, 550, 600, 500]),
    )
    vehicles.write_csv(instance / "vehicles.csv")
    inst = load_instance(instance)
    for routes in (nearest_feasible_neighbor(inst), solve_lns(inst, iterations=150, restarts=1).routes):
        if routes is not None:
            assert check_decision(instance, build_decision(inst, routes))["feasible"]


def test_checker_flags_a_broken_decision():
    decision = json.loads((DATA / "worked-example" / "solution.json").read_text())
    decision["routes"][0]["visits"] = ["C004", "C002", "C003"]   # reversed: misses windows
    decision["routes"][1]["visits"] = decision["routes"][1]["visits"][:-1]  # drops C006
    result = check_decision(DATA / "hand_checkable", decision)
    assert not result["feasible"]
    assert any("C006" in v for v in result["violations"])
    assert any("window end" in v for v in result["violations"])
