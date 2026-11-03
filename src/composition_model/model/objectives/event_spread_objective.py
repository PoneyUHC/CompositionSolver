
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from composition_model.composition_instance import CompositionInstance  # noqa: TC004
    from composition_model.model.composition_encoding import CompositionEncoding  # noqa: TC004
    from composition_model.model.solution import Solution  # noqa: TC004


from composition_model.model.objectives.objective import Objective


class EventSpreadObjective(Objective):
    """How many selected events lie outside the trace that contributes the most.

    Minimizing it makes the split of events across the used traces as uneven as possible:
    one trace is used as far as it can go, and the others only for what it cannot do. Of
    two 6-event certificates over two traces, 5+1 has spread 1 and beats 3+3, which has
    spread 3.

        spread = sum of sel  -  max over traces of (selected events in that trace)

    Why not reward unevenness directly, e.g. maximize the sum of squared per-trace counts?
    That grows with every extra event, so it pays to pad the main trace with events that
    mark nothing. Spread never does: dropping a useless event leaves it equal or lower
    (the total loses one, the max at most one). That is also what `ShrunkInstance` and
    `add_optimizations` require of every term.

    Only the largest trace counts: with three or more traces, 4+4+1+1 and 4+2+2+2 tie.
    """

    name = "spread"

    def build(self, enc: CompositionEncoding):
        model, problem, sel = enc.model, enc.problem, enc.sel
        per_trace = []
        for tr in problem.traces:
            evs = problem.events_of(tr.name)
            c = model.new_int_var(0, len(evs), f"n_selected[{tr.name}]")
            model.add(c == sum(sel[e.id] for e in evs))
            per_trace.append(c)

        n = len(problem.events)
        main = model.new_int_var(0, n, "n_main_trace")
        model.add_max_equality(main, per_trace)
        spread = model.new_int_var(0, self.upper_bound(problem), "spread")
        model.add(spread == sum(sel.values()) - main)
        return spread

    def upper_bound(self, problem: CompositionInstance) -> int:
        # At least one selected event sits in the main trace, so at most n - 1 are outside.
        return max(len(problem.events) - 1, 0)

    def measure(self, problem: CompositionInstance, sol: Solution) -> int | None:
        per_trace = [sum(1 for e in tr.events if sol.selected[e.id]) for tr in problem.traces]
        return sum(per_trace) - max(per_trace, default=0)
