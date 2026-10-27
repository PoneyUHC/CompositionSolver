
from composition_model.model.objectives.objective import Objective  # noqa: I001
from composition_model.model.objectives.selected_events_objective import SelectedEventsObjective
from composition_model.model.objectives.trace_swaps_objective import TraceSwapsObjective

# What gets minimized, most significant first. Change this list to change the question.
DEFAULT_OBJECTIVE: tuple[Objective, ...] = (TraceSwapsObjective(), SelectedEventsObjective())


class ModelOptions:

    objective: tuple[Objective, ...]
    max_seconds: float
    log_search: bool
    show_progress: bool
    num_workers: int
    random_seed: int

    def __init__(
        self,
        objective: tuple[Objective, ...] = DEFAULT_OBJECTIVE,
        max_seconds: float = 360.0,
        log_search: bool = False,
        show_progress: bool = True,
        num_workers: int = 12,
        random_seed: int = 0,
    ) -> None:
        self.objective = tuple(objective)
        self.max_seconds = max_seconds
        self.log_search = log_search
        self.show_progress = show_progress
        self.num_workers = num_workers
        self.random_seed = random_seed


DEFAULT_MODEL_OPTIONS = ModelOptions()