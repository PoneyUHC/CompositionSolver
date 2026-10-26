
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from composition_model.model.Solution import Solution
    from composition_model.CompositionInstance import CompositionInstance
    from composition_model.model.CompositionEncoding import CompositionEncoding


from composition_model.model.objectives.Objective import Objective

class GoalTimeObjective(Objective):
    """When the target gets marked

    """

    name = "time"

    def build(self, enc: CompositionEncoding):
        return enc.t_mk[enc.problem.target]

    def upper_bound(self, problem: CompositionInstance) -> int:
        return problem.max_time

    def measure(self, problem: CompositionInstance, sol: Solution) -> Optional[int]:
        return sol.mark_time[problem.target]