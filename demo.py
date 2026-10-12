"""
Runnable demonstration.   python demo.py

For each example: the hand-derived optimum, the CP-SAT optimum, the brute-force oracle,
whether the certificate passes the independent verifier, and the composed trace itself.
Then: a case where composition is genuinely required.
"""

from __future__ import annotations

import examples
from composition_model import CompositionProblem, Solution, solve, verify
from oracle import brute_force_optimum, search_space_size

LINE = "=" * 92


def fmt(v) -> str:
    return "INFEASIBLE" if v is None else str(v)


def show_certificate(problem: CompositionProblem, sol: Solution, indent: str = "      ") -> None:
    if not sol.ok:
        print(f"{indent}(no certificate: {sol.status})")
        return
    print(f"{indent}composed trace:")
    for t, uid in sol.composed_trace():
        used = ",".join(sol.used_source[uid])
        made = ",".join(f"{d}@{t}" for d in sol.marked_dest[uid])
        print(f"{indent}  t={t}  {uid:16s}  enabled by [{used}]  ->  marks [{made}]")
    marks = ", ".join(f"{x}@{sol.mark_time[x]}" for x in problem.entities if sol.marked[x])
    print(f"{indent}marking: {marks}")
    scores = ", ".join(f"{name}={value}" for name, value in sol.term_values.items())
    print(f"{indent}objective: {scores}; t_mk[{problem.target}] = {sol.mark_time[problem.target]}")


def main() -> None:
    print(LINE)
    print(" CROSS-VALIDATION:  hand-derived  vs  CP-SAT  vs  brute-force oracle  vs  verifier")
    print(LINE)
    # `hand` and `oracle` are both the EARLIEST TIME the target can be marked, which is
    # what the model used to minimize. It now minimizes the certificate's size instead,
    # so cp-sat answers a different question and gets its own two columns: how many
    # events the smallest certificate holds, and when that certificate reaches the
    # target. The second is a valid witness time, so it can only be >= the earliest.
    print(
        f"{'example':22s} {'hand t':>8s} {'oracle t':>9s} {'cp events':>10s} {'cp t':>6s} "
        f"{'verifier':>10s} {'schedules':>10s}  teaches"
    )
    print("-" * 92)
    for ex in examples.ALL:
        sol = solve(ex.problem)
        oracle = brute_force_optimum(ex.problem)
        cp_events = sol.term_values.get("events") if sol.ok else None
        cp_t = sol.mark_time[ex.problem.target] if sol.ok else None
        violations = verify(ex.problem, sol) if sol.ok else []
        vd = "n/a" if not sol.ok else ("OK" if not violations else "REJECTED")
        agree = (
            ex.expected == oracle  # the two independent time derivations still check each other
            and (sol.ok == (oracle is not None))  # and both must agree on reachability
            and (cp_t is None or cp_t >= oracle)  # cp's witness time cannot beat the optimum
            and vd in ("OK", "n/a")
        )
        print(
            f"{ex.name:22s} {fmt(ex.expected):>8s} {fmt(oracle):>9s} {fmt(cp_events):>10s} "
            f"{fmt(cp_t):>6s} {vd:>10s} {search_space_size(ex.problem):>10d}  "
            f"{'' if agree else '<<< MISMATCH '}{ex.teaches}"
        )

    print("\n" + LINE)
    print(" CERTIFICATES (the actual composed traces)")
    print(LINE)
    for ex in examples.ALL:
        print(f"\n  [{ex.name}] target = {ex.problem.target}")
        show_certificate(ex.problem, solve(ex.problem))

    print("\n" + LINE)
    print(" COMPOSITION IS REQUIRED: neither trace reaches G alone")
    print(LINE)
    ex = examples.BY_NAME["composition_required"]
    for t in ("T1", "T2"):
        print(f"  only {t}          -> {solve(ex.problem.restricted_to([t])).status}")
    sol = solve(ex.problem)
    print(f"  T1 + T2 composed -> OPTIMAL, G marked at t={sol.mark_time[ex.problem.target]} "
          f"by {sol.term_values['events']} events")


if __name__ == "__main__":
    main()
