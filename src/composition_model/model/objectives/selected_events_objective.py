
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from composition_model.composition_instance import CompositionInstance  # noqa: TC004
    from composition_model.model.composition_encoding import CompositionEncoding  # noqa: TC004
    from composition_model.model.solution import Solution  # noqa: TC004


from composition_model.model.objectives.objective import Objective


class SelectedEventsObjective(Objective):
    """How many events the certificate contains.

    Without this term selection is free -- nothing obliges a selected event to be useful
    -- so optimal solutions include ones padded with events that mark nothing at all.
    """

    name = "events"

    def build(self, enc: CompositionEncoding):
        v = enc.model.new_int_var(0, len(enc.problem.events), "n_selected")
        enc.model.add(v == sum(enc.sel.values()))
        return v

    def upper_bound(self, problem: CompositionInstance) -> int:
        return len(problem.events)

    def measure(self, problem: CompositionInstance, sol: Solution) -> int | None:
        return sum(1 for on in sol.selected.values() if on)
