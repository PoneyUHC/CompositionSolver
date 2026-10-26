

from collections.abc import Iterable

EntityId = str

class Event:

    name: str
    sources: Iterable[EntityId]
    destinations: Iterable[EntityId]
    id: str
    
    def __init__(
        self,
        name: str,
        sources: Iterable[EntityId],
        destinations: Iterable[EntityId],
        id: str = "",
    ) -> None:
        self.name = name
        self.sources = frozenset(sources)
        self.destinations = frozenset(destinations)
        self.id = id

    def set_id(self, id: str) -> None:
        self.id = id


class Trace:
    name: str
    events: tuple[Event]

    def __init__(
            self, 
            name: str,
            events: Iterable[Event]
    ) -> None:
        self.name = name
        self.events = tuple(events)
        for i, e in enumerate(self.events):
            e.set_id(f"{self.name}[{i}]{e.name}")