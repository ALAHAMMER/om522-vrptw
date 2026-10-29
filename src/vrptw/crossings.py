"""Find where planned routes cross on the map, and test whether uncrossing would help.

Travel times in these instances equal the straight-line distance between the plotting coordinates
(ratio 1.000-1.002), so a crossing on the map is a real geometric crossing. Without time windows, a
crossing inside one route can always be removed by a 2-opt reversal that shortens it. With time
windows the reversal also reverses the visit ORDER, which can make a customer's service start too
late. This module reports, for every crossing inside a route, whether that reversal is feasible and
how much travel it would change, so a map can show why a crossing remains in an optimal plan.

Crossings between two DIFFERENT vehicles are reported but not "fixed": separate trucks may pass the
same spot at different times, and swapping their tails is already one of the LNS moves (2-opt*).
"""

from vrptw.instance import TOL, Instance, route_is_feasible, route_schedule, route_travel


def _orientation(inst: Instance, a: int, b: int, c: int) -> float:
    x, y = inst.x, inst.y
    return (x[b] - x[a]) * (y[c] - y[a]) - (y[b] - y[a]) * (x[c] - x[a])


def _segments_cross(inst: Instance, p: tuple[int, int], q: tuple[int, int]) -> bool:
    """Proper crossing of two segments (shared endpoints and touching do not count)."""
    a, b = p
    c, d = q
    if len({a, b, c, d}) < 4:
        return False
    o1, o2 = _orientation(inst, a, b, c), _orientation(inst, a, b, d)
    o3, o4 = _orientation(inst, c, d, a), _orientation(inst, c, d, b)
    return o1 * o2 < 0 and o3 * o4 < 0


def _crossing_point(inst: Instance, p: tuple[int, int], q: tuple[int, int]) -> tuple[float, float]:
    (a, b), (c, d) = p, q
    x, y = inst.x, inst.y
    denominator = (x[a] - x[b]) * (y[c] - y[d]) - (y[a] - y[b]) * (x[c] - x[d])
    t = ((x[a] - x[c]) * (y[c] - y[d]) - (y[a] - y[c]) * (x[c] - x[d])) / denominator
    return x[a] + t * (x[b] - x[a]), y[a] + t * (y[b] - y[a])


def _why_infeasible(inst: Instance, v: int, route: list[int]) -> str:
    """Name the first constraint a route breaks (windows checked in visit order)."""
    if sum(inst.demand[c] for c in route) > inst.cap[v]:
        return "capacity exceeded"
    _, starts, return_time = route_schedule(inst, v, route)
    for c, start in zip(route, starts):
        if start > inst.we[c] + TOL:
            return f"{inst.ids[c]} would start at {start:.1f}, after its window ends at {inst.we[c]:g}"
    if return_time > inst.shift_end[v] + TOL:
        return f"return at {return_time:.1f}, after the shift ends at {inst.shift_end[v]:g}"
    return ""


def find_crossings(inst: Instance, routes: list[list[int]]) -> list[dict]:
    """Every proper crossing between two legs of the plan, with an uncrossing test for same-route ones."""
    legs = []  # (vehicle index, leg position, (from node, to node))
    for v, route in enumerate(routes):
        if route:
            nodes = [0, *route, 0]
            legs += [(v, k, (nodes[k], nodes[k + 1])) for k in range(len(nodes) - 1)]
    found = []
    for i in range(len(legs)):
        v1, k1, p = legs[i]
        for j in range(i + 1, len(legs)):
            v2, k2, q = legs[j]
            if not _segments_cross(inst, p, q):
                continue
            row = {
                "kind": "same vehicle" if v1 == v2 else "different vehicles",
                "vehicle_1": inst.vehicle_ids[v1], "leg_1": f"{inst.ids[p[0]]}-{inst.ids[p[1]]}",
                "vehicle_2": inst.vehicle_ids[v2], "leg_2": f"{inst.ids[q[0]]}-{inst.ids[q[1]]}",
                "x": 0.0, "y": 0.0,
                "uncross_feasible": None, "uncross_travel_change": None, "why_not": "",
            }
            row["x"], row["y"] = _crossing_point(inst, p, q)
            if v1 == v2:
                route = routes[v1]
                # Legs k1 < k2 cross: reversing the stops between them removes the crossing (2-opt).
                uncrossed = route[:k1] + route[k1:k2][::-1] + route[k2:]
                feasible = route_is_feasible(inst, v1, uncrossed)
                row["uncross_feasible"] = feasible
                row["uncross_travel_change"] = route_travel(inst, uncrossed) - route_travel(inst, route)
                row["why_not"] = "" if feasible else _why_infeasible(inst, v1, uncrossed)
            found.append(row)
    return found


def plot_routes_with_crossings(ax, inst: Instance, routes: list[list[int]], crossings: list[dict], title: str):
    """Route map: one colour per vehicle, red circles on same-vehicle crossings, grey x's between vehicles."""
    import matplotlib.pyplot as plt

    ax.scatter(inst.x[1:], inst.y[1:], s=14, color="#4c78a8", zorder=3)
    ax.scatter([inst.x[0]], [inst.y[0]], marker="*", s=240, color="crimson", zorder=5, label="Depot")
    cmap = plt.get_cmap("tab20")
    for k, route in enumerate(r for r in routes if r):
        xs = [inst.x[0], *[inst.x[c] for c in route], inst.x[0]]
        ys = [inst.y[0], *[inst.y[c] for c in route], inst.y[0]]
        ax.plot(xs, ys, lw=1.4, color=cmap(k % 20), zorder=2)
    same = [c for c in crossings if c["kind"] == "same vehicle"]
    other = [c for c in crossings if c["kind"] == "different vehicles"]
    if other:
        ax.scatter([c["x"] for c in other], [c["y"] for c in other], marker="x", s=36, color="#777777",
                   zorder=4, label=f"{len(other)} crossings between vehicles")
    if same:
        ax.scatter([c["x"] for c in same], [c["y"] for c in same], s=170, facecolors="none",
                   edgecolors="red", linewidths=1.8, zorder=6,
                   label=f"{len(same)} crossings within a route")
    ax.set_title(title, fontsize=10)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    # Below the map, so it never hides a route.
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.01), ncol=3, fontsize=8, frameon=False)
