"""Method 1, the rule to beat: nearest feasible neighbor, one vehicle at a time (option 3 brief).

Take vehicles in identifier order. Each vehicle leaves the depot at its shift start and repeatedly
moves to the nearest unserved customer (by travel time from its current location, ties by customer
identifier) that fits the remaining capacity, can start service by its window end, and still allows
a return to the depot by the shift end. When no customer qualifies, the vehicle returns and the next
vehicle starts. If every vehicle has returned and a customer is unserved, there is no feasible
decision.
"""

from vrptw.instance import TOL, Instance


def nearest_feasible_neighbor(inst: Instance) -> list[list[int]] | None:
    """Return one route (list of customer nodes) per vehicle index, or None if infeasible."""
    T, ws, we, service, demand, ids = inst.T, inst.ws, inst.we, inst.service, inst.demand, inst.ids
    unserved = set(range(1, inst.n + 1))
    routes: list[list[int]] = [[] for _ in inst.vehicle_ids]

    for v in range(len(inst.vehicle_ids)):  # vehicle_ids are already sorted by identifier
        clock, current, load = inst.shift_start[v], 0, 0
        while unserved:
            best_key, best_customer, best_start = None, None, 0.0
            for c in unserved:
                if load + demand[c] > inst.cap[v]:
                    continue                                   # does not fit remaining capacity
                arrival = clock + T[current][c]
                if arrival > we[c] + TOL:
                    continue                                   # cannot start service by window end
                start = arrival if arrival > ws[c] else ws[c]  # wait if early
                if start + service[c] + T[c][0] > inst.shift_end[v] + TOL:
                    continue                                   # could not return by shift end
                key = (T[current][c], ids[c])                  # nearest first, ties by customer id
                if best_key is None or key < best_key:
                    best_key, best_customer, best_start = key, c, start
            if best_customer is None:
                break                                          # vehicle returns to the depot
            routes[v].append(best_customer)
            unserved.remove(best_customer)
            clock = best_start + service[best_customer]
            current = best_customer
            load += demand[best_customer]
        if not unserved:
            break

    return None if unserved else routes
