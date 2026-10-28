"""
What the user types: entity ids (abbreviated or not), and the phase-2 command loop.

`resolve_ids` is shared by the prompt and the command line, so "file1" means the same
thing either way.
"""

import difflib
import re
from collections.abc import Iterable, Sequence

from cli.problem_building import TraceCollection
from cli.report import print_survey, red, solve_and_report
from composition_model.composition_types import EntityId
from composition_model.model.model_options import ModelOptions


def split_ids(text: str) -> list[str]:
    return [x for x in re.split(r"[,\s]+", text.strip()) if x]


def resolve_ids(
    raw: Iterable[str], candidates: Sequence[EntityId], *, label: str
) -> list[EntityId] | None:
    """Resolve what the user typed to ids among `candidates`.

    Entity ids here are whatever the normalizer produced, which for files is an absolute
    path -- far too long to retype. So an input that is not an id itself is accepted when
    it is a substring of exactly one id ("file1", "policy"). Returns None, after saying
    why, if anything was unknown or ambiguous, so an interactive caller can just re-ask.
    """
    known = set(candidates)
    resolved: list[EntityId] = []
    ok = True
    for x in raw:
        if x in known:
            resolved.append(x)
            continue
        hits = [e for e in candidates if x in e]
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


def match_patterns(
    patterns: Iterable[str], candidates: Sequence[EntityId], *, label: str
) -> list[EntityId] | None:
    """Every id among `candidates` that one of `patterns` matches, as a regex searched
    anywhere in the id.

    A plain id or fragment is a regex matching itself, so 'ld.so.cache' still works. But
    unlike `resolve_ids`, a pattern takes every id it matches -- that is the point of
    'fifo:.*-STDERR'. Returns None, after saying why, if a pattern is not a valid regex or
    matches nothing: a typo must not quietly select nothing.
    """
    matched: dict[EntityId, None] = {}  # dict keeps the candidates' order, without repeats
    ok = True
    for p in patterns:
        try:
            rx = re.compile(p)
        except re.error as e:
            print(f"  invalid regex {p!r}: {e}")
            ok = False
            continue
        hits = [x for x in candidates if rx.search(x)]
        if not hits:
            print(f"  no {label} matches {p!r}")
            close = difflib.get_close_matches(p, candidates, n=4)
            if close:
                print(f"    did you mean: {', '.join(close)}")
            ok = False
        elif hits != [p]:  # say what the pattern stood for, unless it was the id itself
            print(f"  {label}: {p} -> " + (hits[0] if len(hits) == 1 else f"{len(hits)} entities"))
        matched.update(dict.fromkeys(hits))
    return list(matched) if ok else None


_PROMPT_HELP = """\
  entry ID [ID ...]    set the entry points: ids marked at t=0, comma- or space-separated.
                       'entry *' takes every candidate entry point listed above.
  goal ID              set the single id to reach.
  remove RE [RE ...]   drop every entity matching one of the regexes from every trace,
                       with every event that mentions it.
  add RE [RE ...]      put back the removed entities matching one of the regexes.
  solve                solve for the current entry points and goal.
  show                 list the traces and entities again; removed entities are in red.
  ? | quit             this help | exit (Ctrl+D works too).

  Without an argument, entry, goal, remove and add print the current value. An id may be
  abbreviated to any substring matching just one entity, so 'file1' stands for its path.
  A regex matches anywhere in an id ('^'/'$' anchor it) and takes every id it matches,
  so 'remove fifo:.*-STDERR' drops all the stderr fifos. Regexes are separated by spaces
  only, so they may contain commas ('{1,3}'); 'a|b' also combines alternatives.
"""


def run_interactive(trace_collection: TraceCollection, options=None) -> int:
    """Phase 2: a command loop. Entry points, goal and removed entities are set in any
    order and kept from one command to the next; `solve` asks the question they form.

    Removal always restarts from `trace_collection`, never from the previous view, so
    `add` is just removing one entity fewer.
    """
    removed: set[EntityId] = set()
    view = trace_collection  # trace_collection without `removed`
    entry: list[EntityId] = []
    goal: EntityId | None = None

    print("\n=== phase 2: ask reachability questions ===")
    print(_PROMPT_HELP)
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        command, _, arg = line.partition(" ")
        command, ids = command.lower(), split_ids(arg)

        if not command:
            continue
        if command in ("quit", "q", "exit"):
            return 0
        if command in ("?", "help"):
            print(_PROMPT_HELP)
        elif command == "show":
            print_survey(view, removed)

        elif command == "entry":
            if arg.strip() == "*":
                entry = list(view.unproduced)
            elif ids:
                resolved = resolve_ids(ids, view.entities, label="entry point")
                entry = resolved if resolved is not None else entry
            print(f"  entry points ({len(entry)}): {', '.join(entry) or '(none)'}")

        elif command == "goal":
            if len(ids) > 1:
                print(f"  give exactly one goal entity (got {len(ids)})")
            elif ids:
                resolved = resolve_ids(ids, view.entities, label="goal")
                goal = resolved[0] if resolved is not None else goal
            print(f"  goal: {goal or '(none)'}")

        elif command in ("remove", "add"):
            patterns = arg.split()  # spaces only: a regex may contain commas
            if patterns:
                if command == "remove":
                    picked = match_patterns(patterns, view.entities, label="entity to remove")
                else:
                    picked = match_patterns(patterns, sorted(removed), label="removed entity")
                if picked is not None:
                    removed = removed | set(picked) if command == "remove" else removed - set(picked)
                    view = trace_collection.remove_entities(removed)
                    print_survey(view, removed)
            shown = ", ".join(red(x) for x in sorted(removed)) or "(none)"
            print(f"  removed ({len(removed)}): {shown}")

        elif command == "solve":
            if not entry or goal is None:
                print("  set the entry points ('entry ...') and the goal ('goal ...') first")
                continue
            # A removal after the question was set can take one of its ids out of every
            # trace: the instance would reject such an entry point, and such a goal is
            # unreachable by construction. Say so rather than solve something else.
            gone = [x for x in (*entry, goal) if x not in view.entities]
            if gone:
                print(f"  no longer in any trace: {', '.join(red(x) for x in gone)}")
                print("  change the entry points or the goal, or 'add' entities back")
                continue
            solve_and_report(view, entry, goal, options)

        else:
            print(f"  unknown command {command!r}; '?' lists the commands")


def handle_non_interactive(
    entry_entities: list[EntityId], 
    goal: EntityId,
    trace_collection: TraceCollection,
    options: ModelOptions
) -> int:
    resolved = resolve_ids(entry_entities, trace_collection.entities, label="entry point")
    if resolved is None:
        return 2
    # Same resolution the prompt gives, so "file1" means the same thing either way.
    # Kept apart from `goal`: the unknown-goal fallback below still needs what was typed.
    resolved_goal = resolve_ids([goal], trace_collection.entities, label="goal")
    if resolved_goal is None:
        if any(goal in e for e in trace_collection.entities):
            return 2  # ambiguous: resolve_ids already listed the candidates
        print(f"warning: goal {goal!r} is not an entity of these traces")
        resolved_goal = [goal]
    solve_and_report(trace_collection, resolved, resolved_goal[0], options)
    return 0