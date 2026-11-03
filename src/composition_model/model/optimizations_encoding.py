
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from composition_model.model.composition_encoding import CompositionEncoding  # noqa: TC004


from composition_model.composition_types import EntityId


def add_optimizations(enc: CompositionEncoding) -> None:
    """Post every redundant constraint below on `enc.model`.

    None of them changes the optimum; they only cut solutions that some other solution,
    at least as good, already beats. That holds as long as every objective term is no
    worse when a selected event that marks nothing is dropped, or when an entity is
    marked earlier. All current terms qualify; check it again before adding a new one.
    `verify` does not re-check them, since they are not part of the semantics.
    """
    add_one_event_per_destination_set(enc)


def add_one_event_per_destination_set(enc: CompositionEncoding) -> None:
    """At most one selected event per destination set.

    Take two selected events with the same destinations D, and e the one that fires first.
    e fires from a source marked before it, so it can mark all of D that is not marked
    yet. Let it: no mark moves later. The other event then marks nothing, so dropping it
    loses nothing (if both fire at the same time, either can be dropped).
    """
    by_destinations: dict[frozenset[EntityId], list] = {}
    for e in enc.problem.events:
        by_destinations.setdefault(e.destinations, []).append(enc.sel[e.id])
    for lits in by_destinations.values():
        if len(lits) > 1:
            enc.model.add_at_most_one(lits)
