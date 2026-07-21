"""
Brute-force reference implementation: the ground truth the CP model is tested against.

The verifier in composition_model.py checks that a returned certificate is valid, but it
cannot tell you whether the *optimum* is right, nor catch an over-constrained encoding that
reports INFEASIBLE when the target is reachable. For that you need a second, independent
computation of the answer -- ideally in a different paradigm. This one has no variables and
no solver: it enumerates every legal schedule and runs a fixpoint. It is exponential, which
is exactly why the examples are tiny.

SEMANTICS
---------
Fix a schedule t_ev respecting trace order. The marking is the least fixpoint

    m(x) = 0                                            x an entry point
    m(d) = min { t_ev(e) : d in dst(e),                 otherwise
                           exists s in src(e) with m(s) < t_ev(e) }

("fire every enabled event, mark all its destinations at its own time, keep the earliest
mark".) The answer is min over schedules of m(target).

EQUIVALENCE WITH THE CP MODEL
-----------------------------
(<=) From any certificate, induction on t_mk gives m(x) <= t_mk(x) for every marked x: the
     event that caused each mark is enabled in the fixpoint no later. So m(target) <= obj.
(>=) From the fixpoint, build a certificate: for each x with m(x) > 0 pick the *earliest*
     enabling event e_x, and set sel(e_x), marks_dst(e_x, x), and use_src(e_x, s) for some
     s with m(s) < t_ev(e_x). Times match by construction. So obj <= m(target).
The two optima coincide. A runtime disagreement therefore means one of the two
implementations is wrong, on an instance small enough to read end to end.
"""

from __future__ import annotations

from itertools import combinations, product
from typing import Optional

from composition_model import CompositionProblem, EntityId


def closure(problem: CompositionProblem, t_ev: dict[str, int]) -> dict[EntityId, int]:
    """Least fixpoint of the marking for a fixed schedule. Returns {entity: mark time}."""
    m: dict[EntityId, int] = {x: 0 for x in problem.entry_entities}

    # Marks are only added and mark times only decrease, over a finite lattice: terminates.
    changed = True
    while changed:
        changed = False
        for e in problem.events:
            te = t_ev[e.id]
            if not any(s in m and m[s] < te for s in e.sources):
                continue
            for d in e.destinations:
                if d not in m or m[d] > te:
                    m[d] = te
                    changed = True
    return m


def legal_schedules(problem: CompositionProblem):
    """Every schedule respecting trace order.

    Times inside a trace are strictly increasing, so a trace's schedule is exactly a
    k-combination of {0..T}: itertools.combinations already emits them sorted and strictly
    increasing. Traces are independent, hence the cartesian product.
    """
    slots = range(problem.max_time + 1)
    per_trace = [list(combinations(slots, len(tr.events))) for tr in problem.traces]
    for choice in product(*per_trace):
        t_ev: dict[str, int] = {}
        for tr, times in zip(problem.traces, choice):
            for ev, t in zip(problem.events_of(tr.name), times):
                t_ev[ev.id] = t
        yield t_ev


def brute_force_optimum(problem: CompositionProblem) -> Optional[int]:
    """min over schedules of m(target). None == unreachable, i.e. INFEASIBLE."""
    best: Optional[int] = None
    for t_ev in legal_schedules(problem):
        m = closure(problem, t_ev)
        if problem.target in m:
            best = m[problem.target] if best is None else min(best, m[problem.target])
            if best == 0:
                return 0  # the target is an entry point; cannot do better
    return best


def search_space_size(problem: CompositionProblem) -> int:
    """How many schedules the oracle will walk. Printed by the demo to keep us honest."""
    n = 1
    for tr in problem.traces:
        k, slots = len(tr.events), problem.max_time + 1
        c = 1
        for i in range(k):
            c = c * (slots - i) // (i + 1)
        n *= c
    return n
