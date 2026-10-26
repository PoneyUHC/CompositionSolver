
from composition_model.composition_types import EntityId


class Solution:
    status: str  # OPTIMAL | FEASIBLE | INFEASIBLE | UNKNOWN
    objective: int | None  # the scalarized value CP-SAT minimized (mixed radix)
    term_values: dict[str, int]  # per objective term, by name -- this is what to read
    selected: dict[str, bool]
    event_time: dict[str, int]
    marked: dict[EntityId, bool]
    mark_time: dict[EntityId, int]
    used_source: dict[str, list[EntityId]]  # witness sources, per selected event
    marked_dest: dict[str, list[EntityId]]  # entities actually marked, per selected event
    wall_time: float

    def __init__(
        self,
        status: str,
        objective: int | None,
        selected: dict[str, bool],
        event_time: dict[str, int],
        marked: dict[EntityId, bool],
        mark_time: dict[EntityId, int],
        used_source: dict[str, list[EntityId]],
        marked_dest: dict[str, list[EntityId]],
        wall_time: float = 0.0,
        term_values: dict[str, int] | None = None,
    ) -> None:
        self.status = status
        self.objective = objective
        self.selected = selected
        self.event_time = event_time
        self.marked = marked
        self.mark_time = mark_time
        self.used_source = used_source
        self.marked_dest = marked_dest
        self.wall_time = wall_time
        self.term_values = term_values or {}

    @property
    def ok(self) -> bool:
        return self.status in ("OPTIMAL", "FEASIBLE")

    def composed_trace(self) -> list[tuple[int, str]]:
        """The answer as a trace: selected events sorted by scheduled time."""
        return sorted((self.event_time[u], u) for u, s in self.selected.items() if s)