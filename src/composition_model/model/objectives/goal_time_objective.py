
from composition_model.composition_instance import CompositionInstance
from composition_model.model.composition_encoding import CompositionEncoding
from composition_model.model.objectives.objective import Objective
from composition_model.model.solution import Solution


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