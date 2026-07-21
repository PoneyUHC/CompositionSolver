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
    print(f"{indent}objective: t_mk[{problem.target}] = {sol.objective}")


def main() -> None:
    print(LINE)
    print(" CROSS-VALIDATION:  hand-derived  vs  CP-SAT  vs  brute-force oracle  vs  verifier")
    print(LINE)
    print(f"{'example':22s} {'hand':>11s} {'cp-sat':>11s} {'oracle':>11s} {'verifier':>10s} {'schedules':>10s}  teaches")
    print("-" * 92)
    for ex in examples.ALL:
        sol = solve(ex.problem)
        oracle = brute_force_optimum(ex.problem)
        cp = sol.objective if sol.ok else None
        violations = verify(ex.problem, sol) if sol.ok else []
        vd = "n/a" if not sol.ok else ("OK" if not violations else "REJECTED")
        agree = (ex.expected == cp == oracle) and vd in ("OK", "n/a")
        print(
            f"{ex.name:22s} {fmt(ex.expected):>11s} {fmt(cp):>11s} {fmt(oracle):>11s} {vd:>10s} "
            f"{search_space_size(ex.problem):>10d}  {'' if agree else '<<< MISMATCH '}{ex.teaches}"
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
    print(f"  T1 + T2 composed -> OPTIMAL, G marked at t={solve(ex.problem).objective}")


if __name__ == "__main__":
    main()
