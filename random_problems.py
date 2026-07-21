"""
Random tiny instance generator, for differential testing against the brute-force oracle.

The hand-written examples prove the model does the right thing on the cases someone thought
of. This attacks the ones nobody thought of. Instances stay small on purpose: the oracle
enumerates C(T+1, k) schedules per trace, and small is what makes exhaustive ground truth
affordable.
"""

from __future__ import annotations

import random

from composition_model import CompositionProblem, event, trace


def random_problem(
    rng: random.Random,
    *,
    n_traces: int = 2,
    max_events_per_trace: int = 2,
    n_entities: int = 4,
    max_sources: int = 2,
    max_dests: int = 2,
) -> CompositionProblem:
    ents = [f"X{i}" for i in range(n_entities)]
    traces = []
    for t in range(n_traces):
        evs = [
            event(
                f"e{i}",
                rng.sample(ents, rng.randint(1, max_sources)),
                rng.sample(ents, rng.randint(1, max_dests)),
            )
            for i in range(rng.randint(1, max_events_per_trace))
        ]
        traces.append(trace(f"T{t}", rng.sample(ents, rng.randint(0, 2)), evs))
    return CompositionProblem(traces=tuple(traces), target=rng.choice(ents))
