"""Method 2, the researched method: Large Neighborhood Search (LNS) for the VRPTW.

Source: Ropke, S., & Pisinger, D. (2006). An adaptive large neighborhood search heuristic for the
pickup and delivery problem with time windows. Transportation Science, 40(4), 455-472.
Local-search moves follow Braysy & Gendreau (2005), Transportation Science 39(1), and the
O(1) insertion test follows Savelsbergh (1992), ORSA Journal on Computing 4(2).

Representation: one list of customer nodes per vehicle (empty list = unused vehicle).

Three phases:
1. Construction: regret-2 insertion builds all routes in parallel. The search starts from the better
   of that solution and the rule-to-beat solution, so it can never end worse than the rule.
2. Improvement: variable neighborhood descent (VND) with five moves, each accepted only if it
   shortens total travel time AND the changed routes pass the full feasibility check.
3. Ruin and recreate: each iteration removes q customers (random, related, or worst), reinserts them
   with regret insertion, runs VND, and accepts the result if it is better, or with a small
   simulated-annealing probability if it is worse. The best solution ever seen is returned.

Phase 3 can optionally be repeated as several independent runs (restarts) from the same starting
plan, each with its own seeded generator, keeping the best plan. With the same total of 8000
iterations, 1x8000, 4x2000, and 8x1000 were within 0.1% of each other on our test instances, so the
default is one run.

Feasibility: every plan the search keeps (current or best) is fully feasible. A ruin step whose
shortened routes break a window (possible when travel times break the triangle inequality) and a
repair that fails are both discarded, and changed routes are re-checked before any acceptance.

Stopping rule: a fixed number of iterations (default 1 run x 8000), with a wall-clock cap only as a
safety net. The cap is checked inside construction, repair, and local search too; when it fires, the
best feasible plan found so far is returned. Run r uses random.Random(seed + r), created once per run (default seed 522), so the same
input and settings always give the same routes.
"""

import math
import random
import time
from dataclasses import dataclass, field

from vrptw.instance import TOL, Instance, route_is_feasible, route_travel
from vrptw.rule import nearest_feasible_neighbor

DEFAULT_ITERATIONS = 8000  # per run
DEFAULT_RESTARTS = 1   # optional independent runs; tuning showed no reliable gain over one long run
DEFAULT_SEED = 522
WORSE_PCT = 0.005  # tuned on development_small, development_medium, and five 60-customer proxies
DEFAULT_TIME_CAP = 480.0  # seconds; the instructor's limit is 600 s for the whole command


@dataclass
class LNSResult:
    routes: list[list[int]] | None
    travel: float = math.inf
    iterations_run: int = 0
    stop_reason: str = ""
    start_method: str = ""
    start_travel: float = math.inf
    history: list[float] = field(default_factory=list)  # best travel after each iteration


# --------------------------------------------------------------------------- route state
class Route:
    """A vehicle's route plus cached timing data that makes insertion checks O(1).

    dep[k]    = time the vehicle leaves position k (position 0 is the depot, at shift start)
    latest[k] = latest service start at position k that keeps every later stop feasible
                (position len+1 is the depot return, whose latest time is the shift end)
    """

    __slots__ = ("inst", "v", "seq", "load", "travel", "dep", "latest")

    def __init__(self, inst: Instance, v: int, seq: list[int]):
        self.inst, self.v, self.seq = inst, v, seq
        self.refresh()

    def refresh(self) -> None:
        inst, seq = self.inst, self.seq
        T, ws, we, service = inst.T, inst.ws, inst.we, inst.service
        nodes = [0, *seq, 0]
        m = len(nodes)
        dep = [0.0] * m
        dep[0] = inst.shift_start[self.v]
        for k in range(1, m - 1):
            c = nodes[k]
            arrival = dep[k - 1] + T[nodes[k - 1]][c]
            dep[k] = (arrival if arrival > ws[c] else ws[c]) + service[c]
        latest = [0.0] * m
        latest[m - 1] = inst.shift_end[self.v]
        for k in range(m - 2, 0, -1):
            c = nodes[k]
            bound = latest[k + 1] - T[c][nodes[k + 1]] - service[c]
            latest[k] = we[c] if we[c] < bound else bound
        self.dep, self.latest = dep, latest
        self.load = sum(inst.demand[c] for c in seq)
        self.travel = route_travel(inst, seq)

    def insertion_cost(self, c: int, pos: int) -> float:
        """Extra travel from inserting customer c before seq[pos]; inf if infeasible. O(1)."""
        inst = self.inst
        if self.load + inst.demand[c] > inst.cap[self.v]:
            return math.inf
        T = inst.T
        before = self.seq[pos - 1] if pos > 0 else 0
        after = self.seq[pos] if pos < len(self.seq) else 0
        arrival = self.dep[pos] + T[before][c]
        start = arrival if arrival > inst.ws[c] else inst.ws[c]
        if start > inst.we[c] + TOL:
            return math.inf
        # Reaching the next stop by its latest start keeps the rest of the route feasible.
        if start + inst.service[c] + T[c][after] > self.latest[pos + 1] + TOL:
            return math.inf
        return T[before][c] + T[c][after] - T[before][after]


def _total(routes: list[Route]) -> float:
    return sum(r.travel for r in routes)


def _snapshot(routes: list[Route]) -> list[list[int]]:
    return [r.seq[:] for r in routes]


def _all_feasible(inst: Instance, routes: list[Route], which=None) -> bool:
    """Full capacity, window, and shift check of the listed routes (all routes by default)."""
    indices = range(len(routes)) if which is None else which
    return all(route_is_feasible(inst, routes[v].v, routes[v].seq) for v in indices)


# --------------------------------------------------------------------------- construction
def regret_insertion(inst: Instance, routes: list[Route], pending: list[int], k: int = 2,
                     rng: random.Random | None = None, deadline: float = math.inf) -> bool:
    """Insert every pending customer; True if all were placed.

    Each step inserts the customer with the largest regret, i.e. the most to lose if its best
    route is taken away: sum over its 2nd..kth best routes of (that cost - best cost). A customer
    that fits in only one route has infinite regret and goes first.
    """
    pending = list(pending)
    demand, cap = inst.demand, inst.cap
    while pending:
        if time.perf_counter() > deadline:
            return False  # out of time: treated like a failed repair
        # Identical empty vehicles give identical insertions, so try only one empty vehicle per
        # (capacity, shift) type. This removes most of the work on fleets with many spare vehicles.
        candidates, empty_types = [], set()
        for ri, r in enumerate(routes):
            if r.seq:
                candidates.append(ri)
            else:
                kind = (cap[r.v], inst.shift_start[r.v], inst.shift_end[r.v])
                if kind not in empty_types:
                    empty_types.add(kind)
                    candidates.append(ri)
        chosen = None  # (priority key, customer, route index, position)
        for c in pending:
            per_route = []
            for ri in candidates:
                r = routes[ri]
                if r.load + demand[c] > cap[r.v]:
                    continue
                best_cost, best_pos = math.inf, -1
                for pos in range(len(r.seq) + 1):
                    cost = r.insertion_cost(c, pos)
                    if cost < best_cost:
                        best_cost, best_pos = cost, pos
                if best_cost < math.inf:
                    per_route.append((best_cost, ri, best_pos))
            if not per_route:
                continue
            per_route.sort()
            best_cost = per_route[0][0]
            regret = (sum(option[0] - best_cost for option in per_route[1:k])
                      if len(per_route) > 1 else math.inf)
            noise = rng.random() * 1e-6 if rng else 0.0  # breaks exact ties reproducibly
            key = (regret + noise, -best_cost, -c)
            if chosen is None or key > chosen[0]:
                chosen = (key, c, per_route[0][1], per_route[0][2])
        if chosen is None:
            return False  # some customer fits nowhere
        _, c, ri, pos = chosen
        routes[ri].seq.insert(pos, c)
        routes[ri].refresh()
        pending.remove(c)
    return True


# --------------------------------------------------------------------------- local search moves
# Every move computes its change in travel from the few edges it alters (O(1)), and only runs
# the full feasibility check on candidates that would shorten the solution.
#
# `dirty` holds the indices of routes that changed since the plan was last at a local optimum.
# A pair of unchanged routes was already checked with no improving move, so only pairs that
# include a dirty route are searched. Routes changed by an accepted move become dirty.

def _two_opt(inst: Instance, r: Route) -> bool:
    """Reverse a segment inside one route (the class's subsequence reversal)."""
    seq, T = r.seq, inst.T
    n = len(seq)
    for i in range(n - 1):
        a = seq[i - 1] if i > 0 else 0
        for j in range(i + 1, n):
            b = seq[j + 1] if j + 1 < n else 0
            # Symmetric travel times: only the two boundary edges change, an O(1) test. Otherwise
            # the reversed inner edges change too, so the exact route cost is compared instead.
            if inst.symmetric:
                improves = T[a][seq[j]] + T[seq[i]][b] - T[a][seq[i]] - T[seq[j]][b] < -TOL
            else:
                improves = route_travel(inst, seq[:i] + seq[i:j + 1][::-1] + seq[j + 1:]) < r.travel - TOL
            if improves:
                candidate = seq[:i] + seq[i:j + 1][::-1] + seq[j + 1:]
                if (route_travel(inst, candidate) < r.travel - TOL
                        and route_is_feasible(inst, r.v, candidate)):
                    r.seq = candidate
                    r.refresh()
                    return True
    return False


def _or_opt(inst: Instance, r: Route) -> bool:
    """Move a block of 1-3 consecutive customers to another place in the same route."""
    seq, T = r.seq, inst.T
    n = len(seq)
    for length in (1, 2, 3):
        for i in range(n - length + 1):
            first, last = seq[i], seq[i + length - 1]
            a = seq[i - 1] if i > 0 else 0
            b = seq[i + length] if i + length < n else 0
            removal_gain = T[a][first] + T[last][b] - T[a][b]
            rest = seq[:i] + seq[i + length:]
            for p in range(len(rest) + 1):
                if p == i:
                    continue
                x = rest[p - 1] if p > 0 else 0
                y = rest[p] if p < len(rest) else 0
                if T[x][first] + T[last][y] - T[x][y] < removal_gain - TOL:
                    candidate = rest[:p] + seq[i:i + length] + rest[p:]
                    if route_is_feasible(inst, r.v, candidate):
                        r.seq = candidate
                        r.refresh()
                        return True
    return False


def _relocate(inst: Instance, routes: list[Route], dirty: set[int]) -> bool:
    """Move one customer to its cheapest feasible position in a different non-empty route."""
    T = inst.T
    for x, r1 in enumerate(routes):
        for i, c in enumerate(r1.seq):
            a = r1.seq[i - 1] if i > 0 else 0
            b = r1.seq[i + 1] if i + 1 < len(r1.seq) else 0
            removal_gain = T[a][c] + T[c][b] - T[a][b]
            for y, r2 in enumerate(routes):
                if y == x or not r2.seq or (x not in dirty and y not in dirty):
                    continue
                for pos in range(len(r2.seq) + 1):
                    if r2.insertion_cost(c, pos) < removal_gain - TOL:
                        shorter = r1.seq[:i] + r1.seq[i + 1:]
                        # The data break the triangle inequality slightly, so check the shortened route.
                        if not route_is_feasible(inst, r1.v, shorter):
                            break
                        r1.seq = shorter
                        r1.refresh()
                        r2.seq.insert(pos, c)
                        r2.refresh()
                        dirty.update((x, y))
                        return True
    return False


def _swap(inst: Instance, routes: list[Route], dirty: set[int]) -> bool:
    """Exchange one customer of one route with one customer of another route."""
    T, demand, cap = inst.T, inst.demand, inst.cap
    for x in range(len(routes)):
        r1 = routes[x]
        for y in range(x + 1, len(routes)):
            if x not in dirty and y not in dirty:
                continue
            r2 = routes[y]
            s1, s2 = r1.seq, r2.seq
            for i, c1 in enumerate(s1):
                a1 = s1[i - 1] if i > 0 else 0
                b1 = s1[i + 1] if i + 1 < len(s1) else 0
                for j, c2 in enumerate(s2):
                    if (r1.load - demand[c1] + demand[c2] > cap[r1.v]
                            or r2.load - demand[c2] + demand[c1] > cap[r2.v]):
                        continue
                    a2 = s2[j - 1] if j > 0 else 0
                    b2 = s2[j + 1] if j + 1 < len(s2) else 0
                    change = (T[a1][c2] + T[c2][b1] - T[a1][c1] - T[c1][b1]
                              + T[a2][c1] + T[c1][b2] - T[a2][c2] - T[c2][b2])
                    if change < -TOL:
                        n1, n2 = s1[:], s2[:]
                        n1[i], n2[j] = c2, c1
                        if route_is_feasible(inst, r1.v, n1) and route_is_feasible(inst, r2.v, n2):
                            r1.seq, r2.seq = n1, n2
                            r1.refresh()
                            r2.refresh()
                            dirty.update((x, y))
                            return True
    return False


def _two_opt_star(inst: Instance, routes: list[Route], dirty: set[int]) -> bool:
    """Exchange the tails of two routes (Potvin & Rousseau 1995); keeps visit direction."""
    T, demand, cap = inst.T, inst.demand, inst.cap
    for x in range(len(routes)):
        r1 = routes[x]
        for y in range(x + 1, len(routes)):
            if x not in dirty and y not in dirty:
                continue
            r2 = routes[y]
            s1, s2 = r1.seq, r2.seq
            if not s1 and not s2:
                continue
            load1 = [0]  # load1[i] = demand of the first i customers of route 1
            for c in s1:
                load1.append(load1[-1] + demand[c])
            load2 = [0]
            for c in s2:
                load2.append(load2[-1] + demand[c])
            for i in range(len(s1) + 1):
                a1 = s1[i - 1] if i > 0 else 0
                b1 = s1[i] if i < len(s1) else 0
                for j in range(len(s2) + 1):
                    a2 = s2[j - 1] if j > 0 else 0
                    b2 = s2[j] if j < len(s2) else 0
                    if T[a1][b2] + T[a2][b1] - T[a1][b1] - T[a2][b2] >= -TOL:
                        continue
                    if (load1[i] + load2[-1] - load2[j] > cap[r1.v]
                            or load2[j] + load1[-1] - load1[i] > cap[r2.v]):
                        continue
                    n1, n2 = s1[:i] + s2[j:], s2[:j] + s1[i:]
                    if route_is_feasible(inst, r1.v, n1) and route_is_feasible(inst, r2.v, n2):
                        r1.seq, r2.seq = n1, n2
                        r1.refresh()
                        r2.refresh()
                        dirty.update((x, y))
                        return True
    return False


def local_search(inst: Instance, routes: list[Route], dirty: set[int] | None = None,
                 deadline: float = math.inf) -> None:
    """Variable neighborhood descent: try cheap moves first, restart after any improvement,
    stop when no move improves (a local optimum for all five neighborhoods).

    dirty: routes changed since the last local optimum (None = all routes, e.g. a new plan)."""
    dirty = set(range(len(routes))) if dirty is None else set(dirty)
    while time.perf_counter() <= deadline:  # every move keeps the plan feasible, so stopping is safe
        if any(_two_opt(inst, routes[x]) or _or_opt(inst, routes[x]) for x in sorted(dirty)):
            continue
        if _relocate(inst, routes, dirty) or _swap(inst, routes, dirty) or _two_opt_star(inst, routes, dirty):
            continue
        return


# --------------------------------------------------------------------------- ruin operators
def _random_removal(inst: Instance, routes: list[Route], q: int, rng: random.Random) -> list[int]:
    customers = [c for r in routes for c in r.seq]
    return rng.sample(customers, min(q, len(customers)))


def _related_removal(inst: Instance, routes: list[Route], q: int, rng: random.Random) -> list[int]:
    """Shaw (1998) removal: a random customer plus those closest to it in travel time and window."""
    customers = [c for r in routes for c in r.seq]
    seed = rng.choice(customers)
    T, ws = inst.T, inst.ws
    customers.sort(key=lambda c: (T[seed][c] + 0.5 * abs(ws[seed] - ws[c]), c))
    return customers[:min(q, len(customers))]


def _worst_removal(inst: Instance, routes: list[Route], q: int, rng: random.Random) -> list[int]:
    """Remove the customers whose detour costs the most (with a little random noise)."""
    T = inst.T
    scored = []
    for r in routes:
        nodes = [0, *r.seq, 0]
        for k in range(1, len(nodes) - 1):
            a, c, b = nodes[k - 1], nodes[k], nodes[k + 1]
            scored.append(((T[a][c] + T[c][b] - T[a][b]) * (0.8 + 0.4 * rng.random()), c))
    scored.sort(reverse=True)
    return [c for _, c in scored[:q]]


# --------------------------------------------------------------------------- main loop
def _ruin_and_recreate(inst: Instance, start_plan: list[list[int]], start_travel: float,
                       iterations: int, rng: random.Random, deadline: float) -> tuple:
    """One LNS run from a starting plan. Returns (best plan, best travel, iterations run, history)."""
    vehicles = range(len(inst.vehicle_ids))
    current, current_travel = start_plan, start_travel
    best, best_travel = start_plan, start_travel
    # Start temperature (Ropke & Pisinger 2006): a plan WORSE_PCT worse than the start is
    # accepted with probability 0.5 at the first iteration; it then cools linearly to zero.
    temperature0 = WORSE_PCT * start_travel / math.log(2)
    max_remove = max(3, min(15, inst.n // 4))
    history = []
    for it in range(1, iterations + 1):
        if time.perf_counter() > deadline:
            return best, best_travel, it - 1, history
        if inst.n < 2:  # nothing to rearrange
            history.append(best_travel)
            continue
        trial = [Route(inst, v, current[v][:]) for v in vehicles]
        # Ruin: remove q customers with one of three operators.
        q = rng.randint(2, max_remove)
        draw = rng.random()
        operator = _random_removal if draw < 0.3 else _related_removal if draw < 0.7 else _worst_removal
        removed = operator(inst, trial, q, rng)
        removed_set = set(removed)
        shortened = []
        for v, r in enumerate(trial):
            if not removed_set.isdisjoint(r.seq):
                r.seq = [c for c in r.seq if c not in removed_set]
                r.refresh()
                shortened.append(v)
        k_regret = rng.choice((2, 3))
        # A shortened route can break a window when travel times break the triangle inequality.
        # Insertion assumes every route it extends is feasible, so such a trial is discarded.
        if not _all_feasible(inst, trial, shortened):
            history.append(best_travel)
            continue
        # Recreate: regret insertion, then local search. A failed repair is simply discarded.
        if regret_insertion(inst, trial, removed, k=k_regret, rng=rng, deadline=deadline):
            changed = {v for v in vehicles if trial[v].seq != current[v]}
            local_search(inst, trial, changed, deadline=deadline)
            if not _all_feasible(inst, trial, changed):  # defence in depth: never keep a broken plan
                history.append(best_travel)
                continue
            trial_travel = _total(trial)
            # Simulated-annealing acceptance: always take improvements, sometimes take a slightly
            # worse plan early on (temperature falls linearly to zero) to escape local optima.
            temperature = temperature0 * (1 - it / iterations)
            accept = trial_travel < current_travel - TOL or (
                temperature > 0
                and rng.random() < math.exp(-(trial_travel - current_travel) / temperature)
            )
            if accept:
                current, current_travel = _snapshot(trial), trial_travel
                if trial_travel < best_travel - TOL:
                    best, best_travel = _snapshot(trial), trial_travel
        history.append(best_travel)
    return best, best_travel, iterations, history


def solve_lns(inst: Instance, iterations: int = DEFAULT_ITERATIONS, seed: int = DEFAULT_SEED,
              restarts: int = DEFAULT_RESTARTS, time_cap: float = DEFAULT_TIME_CAP) -> LNSResult:
    """Construct, improve, then run `restarts` independent ruin-and-recreate runs of `iterations`
    each (seeds seed, seed+1, ...) from the same start, and return the best plan found."""
    deadline = time.perf_counter() + time_cap
    vehicles = range(len(inst.vehicle_ids))

    # Phases 1-2: two starting solutions, each improved by local search; keep the better one.
    starts = []
    regret_routes = [Route(inst, v, []) for v in vehicles]
    if regret_insertion(inst, regret_routes, list(range(1, inst.n + 1)), deadline=deadline):
        local_search(inst, regret_routes, deadline=deadline)
        if _all_feasible(inst, regret_routes):
            starts.append((_total(regret_routes), "regret insertion", _snapshot(regret_routes)))
    rule_plan = nearest_feasible_neighbor(inst)  # fast and always run, so a plan exists even at the cap
    if rule_plan is not None:
        rule_routes = [Route(inst, v, list(rule_plan[v])) for v in vehicles]
        local_search(inst, rule_routes, deadline=deadline)
        if _all_feasible(inst, rule_routes):
            starts.append((_total(rule_routes), "rule to beat", _snapshot(rule_routes)))
    if not starts:
        return LNSResult(routes=None, stop_reason="no feasible starting solution")
    starts.sort(key=lambda entry: entry[0])
    start_travel, start_method, start_plan = starts[0]

    # Phase 3: independent ruin-and-recreate runs.
    best, best_travel = start_plan, start_travel
    total_iterations, history = 0, []
    stop_reason = f"completed {restarts} run(s) of {iterations} iterations"
    if time.perf_counter() > deadline:
        stop_reason = f"time cap of {time_cap:g} s reached during construction"
        restarts = 0
    for run in range(restarts):
        rng = random.Random(seed + run)  # one generator per run, created once
        plan, travel, done, run_history = _ruin_and_recreate(
            inst, start_plan, start_travel, iterations, rng, deadline)
        total_iterations += done
        history.extend(min(best_travel, h) for h in run_history)
        if travel < best_travel - TOL:
            best, best_travel = plan, travel
        if done < iterations:
            stop_reason = f"time cap of {time_cap:g} s reached during run {run + 1}"
            break

    return LNSResult(routes=best, travel=best_travel, iterations_run=total_iterations,
                     stop_reason=stop_reason, start_method=start_method,
                     start_travel=start_travel, history=history)
