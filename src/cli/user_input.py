"""
What the user types: entity ids (abbreviated or not), and the phase-2 prompt loop.

`resolve_ids` is shared by the prompt and the command line, so "file1" means the same
thing either way.
"""

import difflib
import re
from collections.abc import Iterable

from cli.problem_building import TraceCollection
from cli.report import print_survey, solve_and_report
from composition_model.composition_types import EntityId
from composition_model.model.model_options import ModelOptions


def split_ids(text: str) -> list[str]:
    return [x for x in re.split(r"[,\s]+", text.strip()) if x]


def resolve_ids(
    raw: Iterable[str], survey: TraceCollection, *, label: str
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
  entry points   one or more ids marked at t=0, comma- or space-separated.
                 '*' means every candidate entry point listed above.
  goal           the single id to reach.
  shorthand      an id may be abbreviated to any substring matching just one
                 entity, so 'file1' stands for its full path.
  commands       '?' help, 'entities' re-list, blank line or 'quit' to exit.
"""


def run_interactive(survey: TraceCollection, options=None) -> int:
    """Phase 2: ask for an entry set and a goal, solve, repeat."""
    print("\n=== phase 2: ask a reachability question ===")
    print(_PROMPT_HELP)
    while True:
        try:
            line = input("entry points> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if line.lower() in ("", "quit", "q", "exit"):
            return 0
        if line in ("?", "help"):
            print(_PROMPT_HELP)
            continue
        if line.lower() == "entities":
            print_survey(survey)
            continue

        if line == "*":
            entry: list[EntityId] | None = list(survey.unproduced)
            print(f"  ({len(entry)} candidate entry points)")
        else:
            entry = resolve_ids(split_ids(line), survey, label="entry point")
        if entry is None:
            continue

        try:
            line = input("goal> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if line in ("", "quit", "q", "exit"):
            return 0
        goal = resolve_ids(split_ids(line), survey, label="goal")
        if goal is None:
            continue
        if len(goal) != 1:
            print(f"  give exactly one goal entity (got {len(goal)})")
            continue

        solve_and_report(survey, entry, goal[0], options)


def handle_non_interactive(
    entry_entities: list[EntityId], 
    goal: EntityId,
    trace_collection: TraceCollection,
    options: ModelOptions
) -> int:
    resolved = resolve_ids(entry_entities, trace_collection, label="entry point")
    if resolved is None:
        return 2
    # Same resolution the prompt gives, so "file1" means the same thing either way.
    # Kept apart from `goal`: the unknown-goal fallback below still needs what was typed.
    resolved_goal = resolve_ids([goal], trace_collection, label="goal")
    if resolved_goal is None:
        if any(goal in e for e in trace_collection.entities):
            return 2  # ambiguous: resolve_ids already listed the candidates
        print(f"warning: goal {goal!r} is not an entity of these traces")
        resolved_goal = [goal]
    solve_and_report(trace_collection, resolved, resolved_goal[0], options)
    return 0