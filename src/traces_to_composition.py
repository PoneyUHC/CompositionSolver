"""
Trace-to-composition adapter.

Reads a folder of provenance-trace JSON files and turns them into a
`CompositionInstance` (see the `composition_model` package), so the CP-SAT reachability solver
can answer "can this entity be reached by composing these recorded traces, and by when?".

Runs in two phases, because the second needs the first to be answerable at all:

    phase 1  `parse_traces` + `TraceSurvey`: read the files, normalize every entity
             ref, and report the metrics, the normalized entities and the entry-point
             candidates. Nothing is asked of the traces yet.
    phase 2  `build_problem`: the caller picks an entry set and a goal from what
             phase 1 showed, and that becomes a `CompositionInstance` to solve. Cheap
             and repeatable -- the files are parsed once and reused for every question.

`main` wires the two together: it prints the survey, then prompts for an entry set and
a goal (or takes them from the command line). `load_trace` / `load_composition_problem`
collapse both phases into one call for callers that already know what to ask.

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
    one file            -> one ParsedTrace -> one Trace (name = file stem, file order)
    source_entities     -> Event.sources        target_entities -> Event.destinations
    entry entities      -> CompositionInstance.entry_entities, supplied by the caller (see below)

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

ENTITY IDENTITY
---------------
"p:N"/"r:N" are *per-file* indices: r:19 in one file is unrelated to r:19 in another.
`composition_model` joins entities by name *across* traces, so refs must first be resolved
to a global identity. That resolution is delegated to a caller-supplied `normalize`
function, handed a `ResolvedRef` (kind, path/name, resource_type, pid, role). Its
contract: within a single trace it must map distinct refs to distinct ids -- two entities
of one trace must never collapse into one. `parse_trace` checks this and raises if it is
violated.

Pulling in the opposite direction is the need to join: ids must be the *same* across
traces wherever the entity is, or there is no composition to find. So the default
normalizer drops what is per-recording and keeps what is not. A resource keeps its path.
A std fifo loses the pid in "<proc>-<pid>-STDIN", so each process's stdin is one entity
across traces, and the shared comms fifos (fifo_router_to_access, ...) already join by
path -- exactly the cross-trace communication the composition model composes over.

That leaves the processes, where the two pulls collide: the trace files name all three
user processes "user", so the name is not injective, while the pid that would separate
them is different in every recording and would separate them everywhere. The way out is
to identify a process by the principal it acts for, which `roles_by_pid` reads off the
role-bearing fifos it talks on -- stable across recordings and meaningful to a reader.
"""

import difflib
import json
import re
from collections.abc import Callable, Iterable
from pathlib import Path

from composition_model.composition_instance import CompositionInstance
from composition_model.composition_types import EntityId, Event, Trace
from composition_model.model.composition_solver import CompositionSolver
from composition_model.model.model_options import ModelOptions

# =======================================================================================
# Resolving a per-file "p:N" / "r:N" ref to its metadata
# =======================================================================================


class ResolvedRef:
    """A `p:N` / `r:N` reference resolved against its file's process/resource tables.

    This is the object handed to a `Normalizer`. `kind` is "process" or "resource".
    Only the fields relevant to that kind are populated; the rest are None.
    """

    raw: str  # the original "p:N" / "r:N" ref
    kind: str  # "process" | "resource"
    name: str | None  # process name
    pid: int | None  # process pid
    path: str | None  # resource path
    resource_type: int | None  # resource type code
    role: str | None  # the principal this belongs to, when known (see `roles_by_pid`)

    def __init__(
        self,
        raw: str,
        kind: str,
        *,
        name: str | None = None,
        pid: int | None = None,
        path: str | None = None,
        resource_type: int | None = None,
        role: str | None = None,
    ) -> None:
        self.raw = raw
        self.kind = kind
        self.name = name
        self.pid = pid
        self.path = path
        self.resource_type = resource_type
        self.role = role

    def __repr__(self) -> str:
        return f"ResolvedRef({self.raw!r}, {self.kind!r})"


Normalizer = Callable[[ResolvedRef], EntityId]

# A convention of the recorded system, not of traces in general: the comms fifos name
# the principal at each end ("fifo_comm_to_u1", "fifo_u1_to_router").
_ROLE_FIFO_RE = re.compile(r"fifo_(?:comm|router)_to_(u1|u2|admin)$|fifo_(u1|u2|admin)_to_router$")


def roles_by_pid(data: dict) -> dict[int, str]:
    """pid -> the principal that process acts for ("u1", "u2", "admin"), where clear.

    The trace files give every user process the same name, "user", so the name alone
    cannot tell three distinct principals apart -- and pids cannot either, since they
    differ in every recording and so would stop entities joining across traces. What is
    both stable and meaningful is which role-bearing fifo a process talks on.

    A process is assigned a role only when it touches the fifos of exactly one: that is
    true of each `user` process, and deliberately not of `router`, which relays all
    three and keeps its own name. Processes touching none (auth, access) get no role.
    """
    resources = data.get("resources", [])
    processes = data.get("processes", [])
    touched: dict[int, set[str]] = {}
    for ev in data.get("events", []):
        proc = ev.get("process")
        if not isinstance(proc, str) or not proc.startswith("p:"):
            continue
        idx = int(proc[2:])
        for raw in (*ev.get("source_entities", ()), *ev.get("target_entities", ())):
            if not raw.startswith("r:"):
                continue
            m = _ROLE_FIFO_RE.search(resources[int(raw[2:])].get("path") or "")
            if m:
                touched.setdefault(idx, set()).add(m.group(1) or m.group(2))

    roles: dict[int, str] = {}
    for idx, found in touched.items():
        pid = processes[idx].get("pid")
        if len(found) == 1 and pid is not None:
            roles[pid] = next(iter(found))
    return roles


def default_normalizer(ref: ResolvedRef) -> EntityId:
    """Resource -> its path; process -> "proc:<role or name>".

    A std fifo is named "<proc>-<pid>-STDIN"; the pid is dropped so the fifo joins across
    traces, and the owner is named by role where it has one, since three processes share
    the name "user". That keeps every id unique within a file, as the injective-per-trace
    contract requires, while still joining shared entities across traces.
    """
    if ref.kind == "resource":
        if ref.resource_type == 0:
            name_parts = ref.path.split("-")
            if len(name_parts) == 3 and name_parts[2] in ("STDIN", "STDOUT", "STDERR"):
                return f"fifo:{ref.role or name_parts[0]}-{name_parts[2]}"
        return ref.path

    elif ref.kind == "process":
        return f"proc:{ref.role or ref.name}"


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


# =======================================================================================
# Phase 1: parsing
# =======================================================================================


class ParsedTrace:
    """One trace file, read and normalized.

    Phase 1 produces these. Which entities are given for free is a phase-2 question
    (see ENTRY ENTITIES), and not a property of a trace at all.
    """

    name: str
    events: tuple[Event, ...]
    entities: frozenset[EntityId]  # every id this file mentions
    produced: frozenset[EntityId]  # the ids some event of this file marks

    def __init__(
        self,
        name: str,
        events: Iterable[Event],
        entities: Iterable[EntityId],
        produced: Iterable[EntityId],
    ) -> None:
        self.name = name
        self.events = tuple(events)
        self.entities = frozenset(entities)
        self.produced = frozenset(produced)

    def __repr__(self) -> str:
        return f"ParsedTrace({self.name!r}, {len(self.events)} events)"

    def to_trace(self) -> Trace:
        """A `Trace` over these events.

        Calling this once per question is safe: `Trace` stamps event ids from (trace
        name, index, event name), none of which changes, so every call reproduces the
        same ids over the same shared `Event` objects.
        """
        return Trace(self.name, self.events)


def parse_trace(path: Path, normalize: Normalizer = default_normalizer) -> ParsedTrace:
    """Read one trace file and normalize its entity refs.

    Events keep their file order (the files are already timestamp-sorted). Raises if
    `normalize` collapses two of the file's refs to one id.
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
    mentioned: set[EntityId] = set()
    produced: set[EntityId] = set()
    for i, ev in enumerate(data.get("events", [])):
        sources = {norm(r) for r in ev["source_entities"]}
        dests = {norm(r) for r in ev["target_entities"]}
        # The model requires non-empty source/destination sets. Normalization can only
        # shrink a set (by merging refs), never empty a non-empty one, but guard anyway.
        if not sources or not dests:
            continue
        mentioned |= sources | dests
        produced |= dests
        # Readable name; Trace() re-stamps a context-unique id from it.
        events.append(Event(f"{ev['event_type']}#{i}", sources, dests))

    return ParsedTrace(path.stem, events, mentioned, produced)


def parse_traces(
    folder: Path,
    normalize: Normalizer = default_normalizer,
    *,
    glob: str = "*.json",
) -> tuple[ParsedTrace, ...]:
    """Parse every matching trace file in `folder`, sorted by name for determinism."""
    folder = Path(folder)
    files = sorted(folder.glob(glob))
    if not files:
        raise FileNotFoundError(f"no files matching {glob!r} in {folder}")
    return tuple(parse_trace(f, normalize) for f in files)


class TraceSurvey:
    """What phase 1 can say about a collection before any question is asked of it.

    `unproduced` is the useful part: no event marks those entities, so they are the ids
    that *must* be given as entry points to play any role. Everything else is derivable
    in principle -- a process, for instance, is marked by its own open events -- though
    whether it is derivable from a particular entry set is exactly the phase-2 question.
    """

    parsed: tuple[ParsedTrace, ...]
    entities: tuple[EntityId, ...]  # sorted, joined across traces
    produced: frozenset[EntityId]

    def __init__(self, parsed: Iterable[ParsedTrace]) -> None:
        self.parsed = tuple(parsed)
        self.produced = frozenset(x for p in self.parsed for x in p.produced)
        self.entities = tuple(sorted({x for p in self.parsed for x in p.entities}))

    @property
    def n_events(self) -> int:
        return sum(len(p.events) for p in self.parsed)

    @property
    def unproduced(self) -> tuple[EntityId, ...]:
        return tuple(x for x in self.entities if x not in self.produced)

    def knows(self, entity: EntityId) -> bool:
        return entity in self.produced or any(entity in p.entities for p in self.parsed)


# =======================================================================================
# Phase 2: building a question
# =======================================================================================


def build_problem(
    parsed: Iterable[ParsedTrace],
    target: EntityId,
    *,
    entry_entities: Iterable[EntityId],
) -> CompositionInstance:
    """Turn parsed traces plus a caller's entry set and target into a `CompositionInstance`.

    Raises if an entry entity is mentioned by no trace: that is normally a typo in a
    normalized id, which would otherwise quietly weaken the problem.
    """
    parsed = tuple(parsed)
    entry = set(entry_entities)
    unknown = entry - {x for p in parsed for x in p.entities}
    if unknown:
        raise ValueError(f"entry entities mentioned by no trace: {sorted(unknown)}")
    traces = tuple(p.to_trace() for p in parsed)
    return CompositionInstance(traces=traces, target=target, entry_entities=entry)


def load_trace(path: Path, normalize: Normalizer = default_normalizer) -> Trace:
    """Parse one file straight into a `Trace`."""
    return parse_trace(path, normalize).to_trace()


def load_composition_problem(
    folder: Path,
    target: EntityId,
    normalize: Normalizer = default_normalizer,
    *,
    entry_entities: Iterable[EntityId],
    glob: str = "*.json",
) -> CompositionInstance:
    """Both phases at once, for a folder: parse every trace and pose one question."""
    parsed = parse_traces(folder, normalize, glob=glob)
    return build_problem(parsed, target, entry_entities=entry_entities)


# =======================================================================================
# CLI
# =======================================================================================


def print_survey(survey: TraceSurvey, *, list_entities: bool = True) -> None:
    """Phase 1's report: metrics, the normalized entities, and the entry-point candidates."""
    print("=== phase 1: parsed traces ===")
    print(f"trace files: {len(survey.parsed)}")
    print(f"events:      {survey.n_events}")
    print(f"entities:    {len(survey.entities)}")
    width = max((len(p.name) for p in survey.parsed), default=0)
    for p in survey.parsed:
        print(f"  {p.name:<{width}}  {len(p.events):>5} events  {len(p.entities):>4} entities")

    if list_entities:
        print(f"\nnormalized entities ({len(survey.entities)})   [* = no event produces it]")
        for x in survey.entities:
            print(f"  {'*' if x not in survey.produced else ' '} {x}")

    unproduced = survey.unproduced
    print(f"\ncandidate entry points ({len(unproduced)}) -- no event can ever mark these:")
    for x in unproduced:
        print(f"    {x}")


def _show_certificate(problem: CompositionInstance, sol, indent: str = "  ") -> None:
    # Mirrors demo.show_certificate so the composed trace reads as a checkable proof.
    if not sol.ok:
        print(f"{indent}(no certificate: {sol.status})")
        return
    print(f"{indent}composed trace:")
    for t, uid in sol.composed_trace():
        used = ",".join(sol.used_source[uid])
        made = ",".join(f"{d}@{t}" for d in sol.marked_dest[uid])
        print(f"{indent}  t={t}  {uid}  enabled by [{used}]  ->  marks [{made}]")
    scores = ", ".join(f"{name}={value}" for name, value in sol.term_values.items())
    print(f"{indent}objective: {scores}; t_mk[{problem.target}] = {sol.mark_time[problem.target]}")


def _solve_and_report(
    survey: TraceSurvey, entry: list[EntityId], goal: EntityId, options=None
) -> None:
    problem = build_problem(survey.parsed, goal, entry_entities=entry)
    options = options if options is not None else ModelOptions()
    terms = ", ".join(t.name for t in options.objective)
    print(f"\nsolving: {len(problem.entry_entities)} entry entities -> {goal}")
    print(f"minimizing: {terms}")
    sol = CompositionSolver.solve(problem, options)
    print(f"status:   {sol.status}")
    if sol.ok:
        violations = CompositionSolver.verify(sol, problem, options)
        print(f"verifier: {'OK' if not violations else 'REJECTED: ' + '; '.join(violations)}")
        _show_certificate(problem, sol)
    print()


def _split_ids(text: str) -> list[str]:
    return [x for x in re.split(r"[,\s]+", text.strip()) if x]


def _resolve_ids(
    raw: Iterable[str], survey: TraceSurvey, *, label: str
) -> list[EntityId] | None:
    """Resolve what the user typed to entity ids.

    Entity ids here are whatever the normalizer produced, which for files is an absolute
    path -- far too long to retype. So an input that is not an id itself is accepted when
    it is a substring of exactly one id ("file1", "policy"). Returns None, after saying
    why, if anything was unknown or ambiguous, so an interactive caller can just re-ask.
    """
    known = set(survey.entities)
    resolved: list[EntityId] = []
    ok = True
    for x in raw:
        if x in known:
            resolved.append(x)
            continue
        hits = [e for e in survey.entities if x in e]
        if len(hits) == 1:
            print(f"  {label}: {x} -> {hits[0]}")
            resolved.append(hits[0])
            continue
        ok = False
        if hits:
            print(f"  ambiguous {label} {x!r} matches {len(hits)} entities:")
            for e in hits[:8]:
                print(f"    {e}")
            if len(hits) > 8:
                print(f"    ... and {len(hits) - 8} more")
        else:
            print(f"  unknown {label}: {x!r}")
            close = difflib.get_close_matches(x, known, n=4)
            if close:
                print(f"    did you mean: {', '.join(close)}")
    return resolved if ok else None


_PROMPT_HELP = """\
  entry points   ids marked at t=0, comma- or space-separated.
                 '*' means every candidate entry point listed above.
  goal           the single id to reach.
  shorthand      an id may be abbreviated to any substring matching just one
                 entity, so 'file1' stands for its full path.
  commands       '?' help, 'entities' re-list, blank line or 'quit' to exit.
"""


def run_interactive(survey: TraceSurvey, options=None) -> int:
    """Phase 2: ask for an entry set and a goal, solve, repeat."""
    print("\n=== phase 2: ask a reachability question ===")
    print(_PROMPT_HELP)
    while True:
        try:
            line = input("entry points> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if line in ("", "quit", "q", "exit"):
            return 0
        if line in ("?", "help"):
            print(_PROMPT_HELP)
            continue
        if line == "entities":
            print_survey(survey)
            continue

        if line == "*":
            entry: list[EntityId] | None = list(survey.unproduced)
            print(f"  ({len(entry)} candidate entry points)")
        else:
            entry = _resolve_ids(_split_ids(line), survey, label="entry point")
        if entry is None:
            continue

        try:
            line = input("goal> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if line in ("", "quit", "q", "exit"):
            return 0
        goal = _resolve_ids(_split_ids(line), survey, label="goal")
        if goal is None:
            continue
        if len(goal) != 1:
            print(f"  give exactly one goal entity (got {len(goal)})")
            continue

        _solve_and_report(survey, entry, goal[0], options)


def main(
    argv: list[str] | None = None, normalize: Normalizer = default_normalizer
) -> int:
    """Both phases, as a program. `normalize` is a parameter because the entity-identity
    policy is collection-specific: a script with its own normalizer can reuse all of
    this by calling `main(normalize=...)`."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Phase 1 parses a folder of trace JSON files and reports what is in "
        "them; phase 2 asks for an entry set and a goal and solves for reachability."
    )
    parser.add_argument("folder", help="folder containing the trace collection")
    parser.add_argument(
        "goal",
        nargs="?",
        help="normalized entity id to reach. Given together with --entry, phase 2 runs "
        "once from the command line instead of prompting.",
    )
    parser.add_argument(
        "--entry",
        action="append",
        default=[],
        metavar="ENTITY",
        help="normalized entity id marked at t=0; repeat the flag or comma-separate ids.",
    )
    parser.add_argument("--glob", default="*.json", help="file glob (default: *.json)")
    parser.add_argument(
        "--no-entities", action="store_true", help="omit the full entity listing in phase 1"
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=ModelOptions().max_seconds,
        help="solver time limit in seconds (default: %(default)s). Minimizing the event "
        "count is a much harder search than the old time objective, so a short limit "
        "can return UNKNOWN on a large collection.",
    )
    parser.add_argument(
        "--silent", action="store_true", help="do not print a line per improving solution"
    )
    args = parser.parse_args(argv)
    options = ModelOptions(max_seconds=args.max_seconds, show_progress=not args.silent)

    # ---- phase 1: parse and describe, before any question is posed ----
    survey = TraceSurvey(parse_traces(args.folder, normalize, glob=args.glob))
    print_survey(survey, list_entities=not args.no_entities)

    # ---- phase 2: the question, from the command line or interactively ----
    entry = [x for chunk in args.entry for x in _split_ids(chunk)]
    if entry or args.goal is not None:
        if not entry or args.goal is None:
            parser.error("a non-interactive run needs both --entry and a goal")
        resolved = _resolve_ids(entry, survey, label="entry point")
        if resolved is None:
            return 2
        # Same resolution the prompt gives, so "file1" means the same thing either way.
        goal = _resolve_ids([args.goal], survey, label="goal")
        if goal is None:
            if any(args.goal in e for e in survey.entities):
                return 2  # ambiguous: _resolve_ids already listed the candidates
            print(f"warning: goal {args.goal!r} is not an entity of these traces")
            goal = [args.goal]
        _solve_and_report(survey, resolved, goal[0], options)
        return 0

    return run_interactive(survey, options)


if __name__ == "__main__":
    raise SystemExit(main())
