
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from composition_model.composition_instance import CompositionInstance  # noqa: TC004
    from composition_model.model.composition_encoding import CompositionEncoding  # noqa: TC004
    from composition_model.model.solution import Solution  # noqa: TC004


from composition_model.model.objectives.objective import Objective


class UsedTracesObjective(Objective):
    """How many traces the certificate draws at least one event from.

    Minimizing it prefers certificates that compose as few recordings as possible. It says
    nothing about how they interleave: two traces used in long alternation cost the same as
    two traces used one after the other.

    used[tr] <=> OR of sel[e] over the events of tr. Both directions are posted, not just
    sel => used: the objective alone would push used down, but only at optimality -- a
    FEASIBLE answer cut off by the time limit could still report a trace it never uses, and
    `verify` would flag the mismatch.

    Unlike TraceSwaps this posts no NoOverlap, so selected events may share a time again.
    """

    name = "traces"

    def build(self, enc: CompositionEncoding):
        model, problem, sel = enc.model, enc.problem, enc.sel
        used = []
        for tr in problem.traces:
            evs = problem.events_of(tr.name)
            if not evs:
                continue  # an empty trace can never be used
            u = model.new_bool_var(f"used[{tr.name}]")
            for e in evs:
                model.add_implication(sel[e.id], u)
            model.add_bool_or([~u] + [sel[e.id] for e in evs])
            used.append(u)

        v = model.new_int_var(0, len(problem.traces), "n_used_traces")
        model.add(v == sum(used))
        return v

    def upper_bound(self, problem: CompositionInstance) -> int:
        return len(problem.traces)

    def measure(self, problem: CompositionInstance, sol: Solution) -> int | None:
        trace_of = {e.id: tr.name for tr in problem.traces for e in tr.events}
        return len({trace_of[uid] for uid, on in sol.selected.items() if on})
