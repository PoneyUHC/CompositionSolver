"""
Trace parsing: one provenance-trace JSON file -> one `Trace`, entity refs normalized.

TRACE FORMAT
------------
Each `*.json` file is a dict with:
    processes  : [{pid, name}, ...]              referenced as "p:<index>"
    resources  : [{path, resource_type}, ...]    referenced as "r:<index>"
    events     : ordered list (by timestamp). Each event has:
                   event_type, timestamp, description, process ("p:N"),
                   source_entities / target_entities (lists of "p:N"/"r:N" refs),
                   input_values, output_values, optional ext_ustack
    _extensions: metadata (ignored)

MAPPING
-------
    one file            -> one Trace (name = file stem, file order)
    source_entities     -> Event.sources        target_entities -> Event.destinations
    "p:N" / "r:N" refs  -> EntityId, through a `Normalizer` (see `cli.normalization`)
    entry entities      -> not here: a question input (see `cli.problem_building`)
"""

import json
import re
from pathlib import Path

from cli.normalization import Normalizer, ResolvedRef, default_normalizer, roles_by_pid
from composition_model.composition_types import EntityId, Event, Trace


class _RefResolver:
    """Turns "p:N" / "r:N" strings into `ResolvedRef`s using one file's tables.

    `roles` is a pid -> role map (see `roles_by_pid`) that it only carries, never
    derives: which principal a pid acts for is a fact about the recorded system, and
    belongs with the normalization policy rather than in this lookup.
    """

    # "<proc>-<pid>-STDIN" -- how a std fifo path names the process that owns it.
    _OWNER_RE = re.compile(r"-(\d+)-(?:STDIN|STDOUT|STDERR)$")

    def __init__(
        self,
        processes: list[dict],
        resources: list[dict],
        roles: dict[int, str] | None = None,
    ) -> None:
        self._processes = processes
        self._resources = resources
        self._roles = roles or {}

    def _role_of_path(self, path: str | None) -> str | None:
        """The role of the process a std fifo belongs to, read off its pid."""
        m = self._OWNER_RE.search(path or "")
        return self._roles.get(int(m.group(1))) if m else None

    def resolve(self, raw: str) -> ResolvedRef:
        kind, _, idx_str = raw.partition(":")
        idx = int(idx_str)
        if kind == "p":
            proc = self._processes[idx]
            return ResolvedRef(
                raw,
                "process",
                name=proc.get("name"),
                pid=proc.get("pid"),
                role=self._roles.get(proc.get("pid")),
            )
        if kind == "r":
            res = self._resources[idx]
            return ResolvedRef(
                raw,
                "resource",
                path=res.get("path"),
                resource_type=res.get("resource_type"),
                role=self._role_of_path(res.get("path")),
            )
        raise ValueError(f"unknown entity ref kind in {raw!r} (expected 'p:' or 'r:')")


def parse_trace(path: Path, normalize: Normalizer = default_normalizer) -> Trace:
    """Read one trace file and normalize its entity refs.

    Events keep their file order (the files are already timestamp-sorted). Raises if
    `normalize` collapses two of the file's refs to one id. The `Trace` is built once
    here and shared by every question: no trace carries question inputs (entry points
    belong to the `CompositionInstance`), so nothing about it changes between questions.
    """
    path = Path(path)
    data = json.loads(path.read_text())
    resolver = _RefResolver(
        data.get("processes", []), data.get("resources", []), roles_by_pid(data)
    )

    # Cache raw-ref -> normalized id, and enforce the injective-per-trace contract:
    # distinct refs must not map to the same id within this trace.
    norm_of: dict[str, EntityId] = {}
    origin_of: dict[EntityId, str] = {}

    def norm(raw: str) -> EntityId:
        if raw in norm_of:
            return norm_of[raw]
        eid = normalize(resolver.resolve(raw))
        prev = origin_of.get(eid)
        if prev is not None and prev != raw:
            raise ValueError(
                f"{path.name}: normalize maps distinct refs {prev!r} and {raw!r} to the "
                f"same entity id {eid!r}; it must be injective within a trace"
            )
        norm_of[raw] = eid
        origin_of[eid] = raw
        return eid

    events: list[Event] = []
    for i, ev in enumerate(data.get("events", [])):
        sources = {norm(r) for r in ev["source_entities"]}
        dests = {norm(r) for r in ev["target_entities"]}
        # The model requires non-empty source/destination sets. Normalization can only
        # shrink a set (by merging refs), never empty a non-empty one, but guard anyway.
        if not sources or not dests:
            continue
        # Readable name; Trace() stamps a context-unique id from it.
        events.append(Event(f"{ev['event_type']}#{i}", sources, dests))

    return Trace(path.stem, events)


def parse_traces(folder: Path, normalize: Normalizer = default_normalizer) -> tuple[Trace, ...]:
    """Parse every `*.json` file in `folder`, sorted by name for determinism."""
    folder = Path(folder)
    files = sorted(folder.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"no *.json trace files in {folder}")
    return tuple(parse_trace(f, normalize) for f in files)
