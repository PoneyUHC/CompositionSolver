
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from composition_model.composition_instance import CompositionInstance  # noqa: TC004
    from composition_model.model.composition_encoding import CompositionEncoding  # noqa: TC004
    from composition_model.model.solution import Solution  # noqa: TC004


from composition_model.model.objectives.objective import Objective


class GoalTimeObjective(Objective):
    """When the target gets marked

    """

    name = "time"

    def build(self, enc: CompositionEncoding):
        return enc.t_mk[enc.problem.target]

    def upper_bound(self, problem: CompositionInstance) -> int:
        return problem.max_time

    def measure(self, problem: CompositionInstance, sol: Solution) -> int | None:
        return sol.mark_time[problem.target]