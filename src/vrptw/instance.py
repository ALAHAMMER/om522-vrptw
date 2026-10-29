"""Load and validate an option 3 instance directory, and index it for fast solving.

Customers become integer nodes 1..n (sorted by customer_id) and the depot is node 0, so the
solvers work with list indices instead of strings. Travel times become a list of lists
`T[i][j]`, which is the fastest structure for one-value-at-a-time lookups in pure Python.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import polars as pl

TOL = 1e-8  # the instructor's tolerance at every window and shift end
MAX_EXACT_INTEGER = 2**53  # largest magnitude a Float64 represents exactly

# Required files and columns with their declared types (DATA_DICTIONARY.md, schema version 4).
REQUIRED_COLUMNS = {
    "depots.csv": {"node_id": "string", "x": "number", "y": "number"},
    "customers.csv": {
        "customer_id": "string",
        "x": "number",
        "y": "number",
        "demand": "integer",
        "service_time": "integer",
        "window_start": "integer",
        "window_end": "integer",
    },
    "vehicles.csv": {
        "vehicle_id": "string",
        "capacity": "integer",
        "shift_start": "integer",
        "shift_end": "integer",
    },
    "travel_times.csv": {"from_id": "string", "to_id": "string", "travel_time": "number"},
}


class InputError(ValueError):
    """Raised for malformed input. The message always names the file and column."""


@dataclass(frozen=True, slots=True)
class Instance:
    ids: list[str]             # ids[0] is the depot, ids[1..n] are customers sorted by id
    vehicle_ids: list[str]     # sorted by id; vehicle index v refers to vehicle_ids[v]
    demand: list[int]          # demand[0] = 0 for the depot
    service: list[float]       # service[0] = 0
    ws: list[float]            # window start (ws[0] = 0)
    we: list[float]            # window end (we[0] = inf)
    cap: list[int]             # capacity per vehicle
    shift_start: list[float]   # per vehicle
    shift_end: list[float]     # per vehicle
    T: list[list[float]]       # T[i][j] travel minutes between nodes i and j
    T_np: np.ndarray           # the same matrix as a NumPy array, for vectorised work
    x: list[float]             # plotting coordinates only
    y: list[float]
    symmetric: bool = False    # T[i][j] == T[j][i] for every pair (enables the O(1) 2-opt test)

    @property
    def n(self) -> int:
        """Number of customers."""
        return len(self.ids) - 1


def _read_csv(folder: Path, name: str, columns: dict[str, str]) -> pl.DataFrame:
    """Read one CSV, check the columns are present, filled, and of the declared type."""
    file = folder / name
    if not file.is_file():
        raise InputError(f"{name}: required file is missing from {folder}")
    try:
        # Read every column as text so that a bad value is reported by file and column.
        raw = pl.read_csv(file, infer_schema=False)
    except Exception as error:  # unreadable or ragged CSV
        raise InputError(f"{name}: file could not be read as CSV ({error})") from error

    out = []
    for column, kind in columns.items():
        if column not in raw.columns:
            raise InputError(f"{name}: required column '{column}' is missing")
        text = raw.get_column(column)
        if text.null_count() or (text.str.strip_chars() == "").any():
            raise InputError(f"{name}: column '{column}' has empty values")
        if kind == "string":
            out.append(text.str.strip_chars())
            continue
        number = text.str.strip_chars().cast(pl.Float64, strict=False)
        bad = number.is_null() | ~number.is_finite()
        if bad.any():
            example = text.filter(bad).head(3).to_list()
            article = "an" if kind == "integer" else "a"
            raise InputError(f"{name}: column '{column}' must be {article} {kind}; found {example}")
        if kind == "integer":
            if (number != number.round(0)).any():
                example = text.filter(number != number.round(0)).head(3).to_list()
                raise InputError(f"{name}: column '{column}' must be an integer; found {example}")
            # Plain integer text is parsed exactly as Int64. Decimal forms such as "60.0" can only come
            # through Float64, which is exact up to 2^53, so any value beyond that is rejected rather
            # than silently rounded.
            exact = text.str.strip_chars().cast(pl.Int64, strict=False)
            too_big = exact.is_null() & (number.abs() >= MAX_EXACT_INTEGER)
            if too_big.any():
                example = text.filter(too_big).head(3).to_list()
                raise InputError(f"{name}: column '{column}' has integers outside the supported range "
                                 f"(64-bit integers, or magnitude below {MAX_EXACT_INTEGER:,} when written "
                                 f"with a decimal point); found {example}")
            number = exact.fill_null(number.cast(pl.Int64))
        out.append(number.alias(column))
    return pl.DataFrame(out)


def load_instance(folder: str | Path) -> Instance:
    """Load an instance directory and apply the four input checks of the project guide."""
    folder = Path(folder)
    if not folder.is_dir():
        raise InputError(f"{folder}: input directory not found")
    tables = {name: _read_csv(folder, name, cols) for name, cols in REQUIRED_COLUMNS.items()}
    depots = tables["depots.csv"]
    customers = tables["customers.csv"]
    vehicles = tables["vehicles.csv"]
    travel = tables["travel_times.csv"]

    # Identifiers that define an entity must be unique.
    for name, frame, key in (
        ("depots.csv", depots, "node_id"),
        ("customers.csv", customers, "customer_id"),
        ("vehicles.csv", vehicles, "vehicle_id"),
    ):
        if frame.get_column(key).is_duplicated().any():
            duplicates = frame.filter(pl.col(key).is_duplicated()).get_column(key).unique().to_list()
            raise InputError(f"{name}: column '{key}' has duplicate identifiers {sorted(duplicates)[:3]}")
    if depots.height != 1:
        raise InputError(f"depots.csv: column 'node_id' must list exactly one depot, found {depots.height}")
    depot = depots.item(0, "node_id")
    if depot in set(customers.get_column("customer_id").to_list()):
        raise InputError(f"customers.csv: column 'customer_id' reuses the depot id {depot}")

    # Positive durations and sensible intervals.
    if (customers.get_column("service_time") <= 0).any():
        raise InputError("customers.csv: column 'service_time' must be positive")
    if (customers.get_column("demand") < 0).any():
        raise InputError("customers.csv: column 'demand' must not be negative")
    if (customers.get_column("window_start") > customers.get_column("window_end")).any():
        raise InputError("customers.csv: column 'window_end' is earlier than 'window_start'")
    if (vehicles.get_column("capacity") < 0).any():
        raise InputError("vehicles.csv: column 'capacity' must not be negative")
    if (vehicles.get_column("shift_start") > vehicles.get_column("shift_end")).any():
        raise InputError("vehicles.csv: column 'shift_end' is earlier than 'shift_start'")
    if (travel.get_column("travel_time") < 0).any():
        raise InputError("travel_times.csv: column 'travel_time' must not be negative")

    # Match by identifier value, never by row position.
    customers = customers.sort("customer_id")
    vehicles = vehicles.sort("vehicle_id")
    ids = [depot, *customers.get_column("customer_id").to_list()]
    known = set(ids)
    for column in ("from_id", "to_id"):
        unknown = set(travel.get_column(column).unique().to_list()) - known
        if unknown:
            raise InputError(f"travel_times.csv: column '{column}' references unknown ids {sorted(unknown)[:3]}")

    # Build the matrix with joins and one vectorised scatter (no Python loop over rows).
    size = len(ids)
    index = pl.DataFrame({"id": ids, "i": np.arange(size, dtype=np.int64)})
    pairs = travel.join(index.rename({"id": "from_id", "i": "a"}), on="from_id").join(
        index.rename({"id": "to_id", "i": "b"}), on="to_id"
    )
    if pairs.select(pl.struct("a", "b").is_duplicated().any()).item():
        raise InputError("travel_times.csv: column 'to_id' lists the same ordered pair more than once")
    if pairs.height != size * size:
        raise InputError(
            f"travel_times.csv: column 'to_id' is missing ordered pairs "
            f"({pairs.height} of {size * size} present)"
        )
    matrix = np.zeros((size, size))
    matrix[pairs.get_column("a").to_numpy(), pairs.get_column("b").to_numpy()] = pairs.get_column(
        "travel_time"
    ).to_numpy()

    def with_depot(column: str, depot_value: float) -> list[float]:
        return [depot_value, *customers.get_column(column).cast(pl.Float64).to_list()]

    return Instance(
        ids=ids,
        vehicle_ids=vehicles.get_column("vehicle_id").to_list(),
        demand=[0, *customers.get_column("demand").to_list()],
        service=with_depot("service_time", 0.0),
        ws=with_depot("window_start", 0.0),
        we=with_depot("window_end", float("inf")),
        cap=vehicles.get_column("capacity").to_list(),
        shift_start=vehicles.get_column("shift_start").cast(pl.Float64).to_list(),
        shift_end=vehicles.get_column("shift_end").cast(pl.Float64).to_list(),
        T=matrix.tolist(),
        T_np=matrix,
        x=[depots.item(0, "x"), *customers.get_column("x").to_list()],
        y=[depots.item(0, "y"), *customers.get_column("y").to_list()],
        symmetric=bool(np.array_equal(matrix, matrix.T)),
    )


def route_schedule(inst: Instance, v: int, route: list[int]) -> tuple[list[float], list[float], float]:
    """Forward pass for one route: arrivals, service starts, and return time.

    The vehicle leaves the depot at its shift start, waits if it arrives before a window opens,
    and departs each customer when service ends.
    """
    T, ws, service = inst.T, inst.ws, inst.service
    clock, previous = inst.shift_start[v], 0
    arrivals, starts = [], []
    for c in route:
        arrival = clock + T[previous][c]
        start = arrival if arrival > ws[c] else ws[c]
        arrivals.append(arrival)
        starts.append(start)
        clock, previous = start + service[c], c
    return arrivals, starts, clock + T[previous][0]


def route_is_feasible(inst: Instance, v: int, route: list[int]) -> bool:
    """Capacity, every window, and the shift end, checked in one forward pass."""
    if sum(inst.demand[c] for c in route) > inst.cap[v]:
        return False
    T, ws, we, service = inst.T, inst.ws, inst.we, inst.service
    clock, previous = inst.shift_start[v], 0
    for c in route:
        arrival = clock + T[previous][c]
        start = arrival if arrival > ws[c] else ws[c]
        if start > we[c] + TOL:
            return False
        clock, previous = start + service[c], c
    return clock + T[previous][0] <= inst.shift_end[v] + TOL


def route_travel(inst: Instance, route: list[int]) -> float:
    """Travel minutes of one route including both depot legs (0 for an empty route)."""
    if not route:
        return 0.0
    T = inst.T
    total = T[0][route[0]] + T[route[-1]][0]
    for a, b in zip(route, route[1:]):
        total += T[a][b]
    return total
