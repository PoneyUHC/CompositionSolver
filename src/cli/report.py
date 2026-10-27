"""
What the CLI prints: the phase-1 survey, and the answer to one question with its certificate.
"""

import signal

from cli.problem_building import TraceCollection, mentioned_entities
from composition_model.composition_instance import CompositionInstance
from composition_model.composition_types import EntityId
from composition_model.model.composition_solver import CompositionSolver
from composition_model.model.model_options import ModelOptions


def print_survey(trace_collection: TraceCollection) -> None:
    """Phase 1's report: metrics, the normalized entities, and the entry-point candidates."""
    print("=== phase 1: parsed traces ===")
    print(f"trace files: {len(trace_collection.traces)}")
    print(f"events:      {trace_collection.n_events}")
    print(f"entities:    {len(trace_collection.entities)}")
    width = max((len(tr.name) for tr in trace_collection.traces), default=0)
    for tr in trace_collection.traces:
        n_entities = len(mentioned_entities(tr))
        print(f"  {tr.name:<{width}}  {len(tr.events):>5} events  {n_entities:>4} entities")

    print(f"\nnormalized entities ({len(trace_collection.entities)})   [* = no event produces it]")
    for x in trace_collection.entities:
        print(f"  {'*' if x not in trace_collection.produced else ' '} {x}")

    unproduced = trace_collection.unproduced
    print(f"\ncandidate entry points ({len(unproduced)}) -- no event can ever mark these:")
    for x in unproduced:
        print(f"    {x}")


def show_certificate(problem: CompositionInstance, sol, indent: str = "  ") -> None:
    # One line per selected event, in time order, so the composed trace reads as a
    # checkable proof.
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


def solve_and_report(
    trace_collection: TraceCollection, entry_entities: list[EntityId], goal: EntityId, options=None
) -> None:
    problem = trace_collection.build_problem(goal, entry_entities=entry_entities)
    options = options if options is not None else ModelOptions()
    terms = ", ".join(t.name for t in options.objective)
    print(f"\nsolving: {len(problem.entry_entities)} entry entities -> {goal}")
    print(f"minimizing: {terms}")
    # Ctrl+C during the search is trapped by CP-SAT itself (`catch_sigint_signal`, on by
    # default): it stops as if the time limit were reached and returns its best solution,
    # so the report below prints as usual. On its way out, though, CP-SAT resets SIGINT to
    # the OS default, after which a Ctrl+C at the prompt would kill the process outright
    # instead of raising KeyboardInterrupt -- so put Python's handler back.
    python_sigint = signal.getsignal(signal.SIGINT)
    try:
        sol = CompositionSolver.solve(problem, options)
    finally:
        signal.signal(signal.SIGINT, python_sigint)
    print(f"status:   {sol.status}")
    if sol.ok:
        violations = CompositionSolver.verify(sol, problem, options)
        print(f"verifier: {'OK' if not violations else 'REJECTED: ' + '; '.join(violations)}")
        show_certificate(problem, sol)
    print()