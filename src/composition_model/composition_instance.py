

from collections.abc import Iterable
from typing import Self

from composition_model.composition_types import EntityId, Event, Trace


class CompositionInstance:
    """The composition graph plus the reachability question asked of it.

    Entities are identified by name across traces: if two traces mention "X", it is the
    same X. Entry points are part of the question, like the target: what is free at t=0 is
    a property of the deployment, not of any recording, so no trace carries them.
    """

    traces: tuple[Trace, ...]
    target: EntityId
    entry_entities: frozenset[EntityId]

    # derived in __init__, never passed by the caller
    events: tuple[Event, ...]  # each stamped with a context-unique id
    entities: tuple[EntityId, ...]
    producers: dict[EntityId, tuple[Event, ...]]  # x -> events that can mark x
    _events_by_trace: dict[str, tuple[Event, ...]]

    def __init__(
        self,
        traces: tuple[Trace, ...],
        target: EntityId,
        *,
        entry_entities: Iterable[EntityId],
    ) -> None:
        # No default for entry_entities: with none, every instance is INFEASIBLE, so a
        # forgotten argument would read as a (wrong) unreachability proof.
        self.traces = tuple(traces)
        self.target = target
        self.entry_entities = frozenset(entry_entities)
        self._events_by_trace = {tr.name: tr.events for tr in self.traces}
        self.events = tuple(ev for tr in self.traces for ev in tr.events)

        # Entries go in even if no event mentions them, so (1) has an mk/t_mk to pin.
        seen: dict[EntityId, None] = {}  # dict keeps insertion order -> deterministic output
        for x in sorted(self.entry_entities):
            seen.setdefault(x, None)
        for ev in self.events:
            for x in sorted(ev.sources) + sorted(ev.destinations):
                seen.setdefault(x, None)
        seen.setdefault(self.target, None)
        self.entities = tuple(seen)

        producers: dict[EntityId, list[Event]] = {x: [] for x in self.entities}
        for ev in self.events:
            for d in ev.destinations:
                producers[d].append(ev)
        self.producers = {x: tuple(v) for x, v in producers.items()}

        self.validate()

    @property
    def max_time(self) -> int:
        return len(self.events)

    def events_of(self, trace_name: str) -> tuple[Event, ...]:
        return self._events_by_trace[trace_name]

    def restricted_to(self, trace_names: Iterable[str]) -> Self:
        keep = set(trace_names)
        # The entry set belongs to the question, so it survives dropping traces.
        return CompositionInstance(
            tuple(t for t in self.traces if t.name in keep),
            self.target,
            entry_entities=self.entry_entities,
        )

    def validate(self) -> None:
        names = [tr.name for tr in self.traces]
        assert len(names) == len(set(names)), f"duplicate trace names: {names}"
        ids = [e.id for e in self.events]
        assert len(ids) == len(set(ids)), f"duplicate event ids: {ids}"
        for e in self.events:
            # Empty source/destination sets make (2)/(3) empty disjunctions, i.e. false, so
            # such an event could never be selected. Legal, but always a mistake.
            assert e.sources, f"{e.id} has no source: it could never be selected"
            assert e.destinations, f"{e.id} has no destination: it could never mark anything"
