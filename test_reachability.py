"""
The methodology, executable.

Four independent sources of truth are cross-checked:
  1. the optimum derived by hand in examples.py, written before anything was run,
  2. the CP-SAT encoding,
  3. the brute-force oracle (different paradigm, no solver),
  4. the semantic verifier (re-checks the returned certificate in pure Python).

Run:  python test_reachability.py     (plain asserts; `pytest test_reachability.py` works too)
"""

from __future__ import annotations

import random

import examples
from composition_model import (
    CompositionProblem,
    CpEncoding,
    ModelOptions,
    _make_solver,
    event,
    solve,
    trace,
    verify,
)
from oracle import brute_force_optimum
from random_problems import random_problem


def test_examples_agree_with_hand_derivation_and_oracle() -> None:
    for ex in examples.ALL:
        sol = solve(ex.problem)
        oracle = brute_force_optimum(ex.problem)

        if ex.expected is None:
            assert sol.status == "INFEASIBLE", f"{ex.name}: expected INFEASIBLE, got {sol.status}"
            assert oracle is None, f"{ex.name}: oracle disagrees, it found {oracle}"
        else:
            assert sol.status == "OPTIMAL", f"{ex.name}: {sol.status}"
            assert sol.objective == ex.expected, f"{ex.name}: CP-SAT {sol.objective} != hand {ex.expected}"
            assert oracle == ex.expected, f"{ex.name}: oracle {oracle} != hand {ex.expected}"
            assert verify(ex.problem, sol) == [], f"{ex.name}: {verify(ex.problem, sol)}"


def test_randomized_differential_against_oracle(n: int = 300, seed: int = 20260716) -> None:
    """The examples cover what was thought of; this covers what was not. Every instance is
    solved twice by unrelated implementations and the certificate is verified. Any
    disagreement is a bug in one of them, on an instance small enough to debug by hand."""
    rng = random.Random(seed)
    reachable = 0
    for i in range(n):
        p = random_problem(rng)
        sol = solve(p)
        oracle = brute_force_optimum(p)
        if oracle is None:
            assert sol.status == "INFEASIBLE", f"case {i}: CP found {sol.objective}, oracle says unreachable"
        else:
            reachable += 1
            assert sol.status == "OPTIMAL", f"case {i}: CP says {sol.status}, oracle says {oracle}"
            assert sol.objective == oracle, f"case {i}: CP {sol.objective} != oracle {oracle}"
            assert verify(p, sol) == [], f"case {i}: {verify(p, sol)}"
    # Guard against a vacuous test: if nothing were reachable, agreement would be cheap.
    assert 0.15 * n < reachable < 0.85 * n, f"unbalanced sample: {reachable}/{n} reachable"


def test_single_traces_cannot_reach_the_target() -> None:
    ex = examples.BY_NAME["composition_required"]
    for t in ("T1", "T2"):
        assert solve(ex.problem.restricted_to([t])).status == "INFEASIBLE", f"{t} alone should not reach G"
    assert solve(ex.problem).objective == 3


def test_certificate_is_well_formed() -> None:
    """Structural properties that must hold on any solved instance."""
    for ex in examples.ALL:
        sol = solve(ex.problem)
        if not sol.ok:
            continue
        for uid, on in sol.selected.items():
            if not on:
                continue
            assert sol.used_source[uid], f"{ex.name}/{uid}: selected without a source witness"
            for s in sol.used_source[uid]:
                assert sol.marked[s] and sol.mark_time[s] < sol.event_time[uid]
            for d in sol.marked_dest[uid]:
                assert sol.mark_time[d] == sol.event_time[uid]


def test_tie_break_returns_a_minimal_certificate() -> None:
    """Nothing forces a selected event to be useful, so the optimal-time solutions include
    padded ones. The lexicographic tie-break picks a minimal certificate without touching
    the objective."""
    ex = examples.BY_NAME["fastest_producer"]

    minimal = solve(ex.problem, ModelOptions(minimize_selected_events=True))
    assert minimal.objective == 1
    assert sum(minimal.selected.values()) == 1, minimal.composed_trace()

    # Exhibit the padding the objective alone permits: maximise selections at the optimum.
    enc = CpEncoding(ex.problem, ModelOptions(), freeze_objective_at=1, secondary="max_selected")
    solver = _make_solver(ModelOptions())
    assert solver.status_name(solver.solve(enc.model)) == "OPTIMAL"
    padded = sum(solver.boolean_value(v) for v in enc.sel.values())
    assert padded > 1, "expected optimal-but-padded certificates to exist"


def test_target_as_entry_point_is_zero() -> None:
    p = CompositionProblem(traces=(trace("T1", ["A"], [event("e1", ["A"], ["B"])]),), target="A")
    sol = solve(p)
    assert sol.objective == 0 and brute_force_optimum(p) == 0
    assert verify(p, sol) == []


def test_max_time_bound_is_sufficient() -> None:
    """Worst case for the bound: one trace holding every event, all of them needed. The
    last event lands exactly on T = |events|; one slot less would be INFEASIBLE."""
    n = 6
    evs = [event(f"e{i}", [f"X{i}"], [f"X{i+1}"]) for i in range(n)]
    p = CompositionProblem(traces=(trace("T", ["X0"], evs),), target=f"X{n}")
    sol = solve(p)
    assert sol.objective == n == p.max_time
    assert verify(p, sol) == []


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  PASS  {t.__name__}")
    print(f"\n{len(tests)} tests passed.")
