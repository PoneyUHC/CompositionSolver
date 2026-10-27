"""
From parsed traces to a `CompositionInstance`: survey the collection, then pose a question.

ENTRY ENTITIES
--------------
What is available for free at t=0 is a question about the deployment, not about the
recording: an entity no trace happens to produce may still be something an attacker
must first obtain. So entry entities are not inferred here -- they are a phase-2 input,
attached to the `CompositionInstance` alongside the goal, never to a `Trace`.

Phase 1 reports the entities that no event produces. Those *must* be entry points to
play any role, so they are the candidates to choose from, but the choice is wider than
that list: any entity may be given for free. A process, for instance, is produced (by
its own open events) and so is derivable rather than required, yet granting it directly
is a perfectly meaningful question to ask.
"""

from collections.abc import Iterable
from pathlib import Path

from cli.normalization import Normalizer, default_normalizer
from cli.trace_parsing import parse_traces
from composition_model.composition_instance import CompositionInstance
from composition_model.composition_types import EntityId, Trace


def mentioned_entities(trace: Trace) -> frozenset[EntityId]:
    """Every id some event of `trace` reads or marks."""
    return frozenset(x for ev in trace.events for x in (*ev.sources, *ev.destinations))


class TraceCollection:
    """What phase 1 can say about a collection before any question is asked of it.

    `unproduced` is the useful part: no event marks those entities, so they are the ids
    that *must* be given as entry points to play any role. Everything else is derivable
    in principle -- a process, for instance, is marked by its own open events -- though
    whether it is derivable from a particular entry set is exactly the phase-2 question.
    """

    traces: tuple[Trace, ...]
    entities: tuple[EntityId, ...]  # sorted, joined across traces
    produced: frozenset[EntityId]

    def __init__(self, traces: Iterable[Trace]) -> None:
        self.traces = tuple(traces)
        self.produced = frozenset(d for tr in self.traces for ev in tr.events for d in ev.destinations)
        self.entities = tuple(sorted({x for tr in self.traces for x in mentioned_entities(tr)}))

    @property
    def n_events(self) -> int:
        return sum(len(tr.events) for tr in self.traces)

    @property
    def unproduced(self) -> tuple[EntityId, ...]:
        return tuple(x for x in self.entities if x not in self.produced)

    def build_problem(
        self, target: EntityId, *, entry_entities: Iterable[EntityId]
    ) -> CompositionInstance:
        """Pose one question of the collection: reach `target` from `entry_entities`.

        Raises if an entry entity is mentioned by no trace: that is normally a typo in a
        normalized id, which would otherwise quietly weaken the problem.
        """
        entry = set(entry_entities)
        unknown = entry.difference(self.entities)
        if unknown:
            raise ValueError(f"entry entities mentioned by no trace: {sorted(unknown)}")
        return CompositionInstance(self.traces, target, entry_entities=entry)


def load_composition_problem(
    folder: Path,
    target: EntityId,
    normalize: Normalizer = default_normalizer,
    *,
    entry_entities: Iterable[EntityId],
) -> CompositionInstance:
    """Both phases at once, for a folder: parse every trace and pose one question."""
    traces = TraceCollection(parse_traces(folder, normalize))
    return traces.build_problem(target, entry_entities=entry_entities)
