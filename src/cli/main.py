"""
Trace-to-composition command line.

Reads a folder of provenance-trace JSON files and turns them into a
`CompositionInstance` (see the `composition_model` package), so the CP-SAT reachability solver
can answer "can this entity be reached by composing these recorded traces, and by when?".

Runs in two phases, because the second needs the first to be answerable at all:

    phase 1  `parse_traces` + `TraceCollection`: read the files, normalize every entity
             ref, and report the metrics, the normalized entities and the entry-point
             candidates. Nothing is asked of the traces yet.
    phase 2  `TraceCollection.build_problem`: the caller picks an entry set and a goal
             from what phase 1 showed, and that becomes a `CompositionInstance` to solve.
             Cheap and repeatable -- the files are parsed once and reused for every question.

`main` wires the two together: it prints the survey, then takes the entry set and goal
from the command line, or runs a command loop where they are set, entities removed or
put back, and the question solved. `load_composition_problem` collapses both phases into
one call for callers that already know what to ask.

Modules, one action each:
    cli.normalization     "p:N" / "r:N" ref -> cross-trace EntityId (the identity policy)
    cli.trace_parsing     JSON file -> Trace
    cli.problem_building  Traces -> TraceCollection (minus removed entities), and
                          + entry set + goal -> instance
    cli.report            printing the survey and a solved question
    cli.user_input        resolving typed ids, and the phase-2 command loop
    cli.args              the argument parser
    cli.main              wiring the phases together
"""

from cli.args import build_parser
from cli.normalization import Normalizer, default_normalizer
from cli.problem_building import TraceCollection
from cli.report import print_survey
from cli.trace_parsing import parse_traces
from cli.user_input import handle_non_interactive, run_interactive, split_ids
from composition_model.model.model_options import ModelOptions


def main(
    argv: list[str] | None = None, normalize: Normalizer = default_normalizer
) -> int:

    parser = build_parser()
    args = parser.parse_args(argv)
    options = ModelOptions(max_seconds=args.max_seconds, show_progress=not args.silent)
    # Both flags pose one question; neither means ask interactively. Checked before
    # phase 1 so a malformed command line fails without parsing the whole collection.
    entry_entities = [x for chunk in args.entries for x in split_ids(chunk)]
    if bool(entry_entities) != (args.goal is not None):
        parser.error("a non-interactive run needs both --entries and --goal")

    # ---- phase 1: parse and describe, before any question is posed ----
    parsed_traces = parse_traces(args.folder, normalize)
    trace_collection = TraceCollection(parsed_traces)
    print_survey(trace_collection)

    # ---- phase 2: the question, from the command line or interactively ----
    if entry_entities:
        return handle_non_interactive(entry_entities, args.goal, trace_collection, options)
    return run_interactive(trace_collection, options)


if __name__ == "__main__":
    raise SystemExit(main())
