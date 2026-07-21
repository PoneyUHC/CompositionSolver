"""
Minimal examples.

One example, one phenomenon, and the expected optimum derived by hand in the docstring
before any solver runs. If the solver, the oracle and the hand argument all agree, the
encoding means what it should. If they disagree, the instance is small enough to read the
whole solution and see who is wrong.

Legend: A, B, ... are entities. Entry entities are marked at time 0. An event fires at time
t if one of its sources was marked at some t' < t, and marks its destinations at t.
"""

from __future__ import annotations

from typing import Optional

from composition_model import CompositionProblem, Event, Trace


class Example:
    name: str
    problem: CompositionProblem
    expected: Optional[int]  # None == INFEASIBLE (the target is unreachable)
    teaches: str

    def __init__(
        self,
        name: str,
        problem: CompositionProblem,
        expected: Optional[int],
        teaches: str,
    ) -> None:
        self.name = name
        self.problem = problem
        self.expected = expected
        self.teaches = teaches


# ---------------------------------------------------------------------------------------
# The smallest thing that is not trivial.
#   T1 (entry {A}): e1: A -> B      target B
#   A@0. e1 needs a source marked strictly earlier, so t_ev(e1) >= 1; take 1. B@1.
# ---------------------------------------------------------------------------------------
single_step = Example(
    name="single_step",
    problem=CompositionProblem(
        traces=(Trace("T1", ["A"], [Event("e1", ["A"], ["B"])]),),
        target="B",
    ),
    expected=1,
    teaches="entries at 0, and the strict '<' on sources pushes the first event to 1",
)

# ---------------------------------------------------------------------------------------
# The point of the whole model: the target is reachable only by COMPOSING traces.
#   T1 (entry {A}): e1: A -> X ,  e2: Y -> G
#   T2 (entry {B}): f1: X -> Y
#   target G
# Neither trace alone reaches G: T1's e2 needs Y, which nothing in T1 makes; T2's f1 needs
# X, which nothing in T2 makes. Composed: A@0 -> e1@1 marks X@1 -> f1@2 marks Y@2 -> e2@3
# marks G@3. Lower bound: X >= 1 so f1 >= 2, so Y >= 2, so e2 >= 3. Optimum 3.
# Trace order in T1 (e1 before e2) holds: 1 < 3.
# ---------------------------------------------------------------------------------------
composition_required = Example(
    name="composition_required",
    problem=CompositionProblem(
        traces=(
            Trace("T1", ["A"], [Event("e1", ["A"], ["X"]), Event("e2", ["Y"], ["G"])]),
            Trace("T2", ["B"], [Event("f1", ["X"], ["Y"])]),
        ),
        target="G",
    ),
    expected=3,
    teaches="the composed trace interleaves T1 and T2; each trace alone is INFEASIBLE",
)

# ---------------------------------------------------------------------------------------
# Disjunction over sources: one marked source is enough, and the solver picks the fast one.
#   T1 (entry {A}): e1: A -> X
#   T2 (entry {B}): f1: {X, B} -> G      target G
# f1 needs only ONE marked source. B is an entry, marked at 0, so f1 fires at 1 without
# waiting for X (available at 1, which would push f1 to 2). Optimum 1.
# Same shape as composition_required, minus the B shortcut.
# ---------------------------------------------------------------------------------------
source_disjunction = Example(
    name="source_disjunction",
    problem=CompositionProblem(
        traces=(
            Trace("T1", ["A"], [Event("e1", ["A"], ["X"])]),
            Trace("T2", ["B"], [Event("f1", ["X", "B"], ["G"])]),
        ),
        target="G",
    ),
    expected=1,
    teaches="OR over sources; the witness shows WHICH source enabled the event",
)

# ---------------------------------------------------------------------------------------
# Trace order applies to every event of a trace, selected or not.
#   T1 (entry {A}): n1: A -> J1 ,  n2: J1 -> J2 ,  e3: A -> G      target G
# e3 needs only A, marked at 0, so G looks reachable at 1. But trace order gives
# t(n1) < t(n2) < t(e3), hence t(e3) >= 2 and G@2: an event cannot fire before its own
# prefix has consumed that many slots, even though n1 and n2 are not selected.
# ---------------------------------------------------------------------------------------
trace_order_delay = Example(
    name="trace_order_delay",
    problem=CompositionProblem(
        traces=(
            Trace(
                "T1",
                ["A"],
                [Event("n1", ["A"], ["J1"]), Event("n2", ["J1"], ["J2"]), Event("e3", ["A"], ["G"])],
            ),
        ),
        target="G",
    ),
    expected=2,
    teaches="trace order over all events implies t_ev(e) >= index(e), even for unselected ones",
)

# ---------------------------------------------------------------------------------------
# Competing producers: the objective chooses.
#   T1 (entry {A}): e1: A -> G
#   T2 (entry {A}): f1: A -> P , f2: P -> Q , f3: Q -> G      target G
# Both reach G; T1 at 1, T2 at 3. Optimum 1 via T1, with a one-event certificate.
# ---------------------------------------------------------------------------------------
fastest_producer = Example(
    name="fastest_producer",
    problem=CompositionProblem(
        traces=(
            Trace("T1", ["A"], [Event("e1", ["A"], ["G"])]),
            Trace("T2", ["A"], [Event("f1", ["A"], ["P"]), Event("f2", ["P"], ["Q"]), Event("f3", ["Q"], ["G"])]),
        ),
        target="G",
    ),
    expected=1,
    teaches="min t_mk(target) discriminates between alternative data flows",
)

# ---------------------------------------------------------------------------------------
# The unfounded cycle. This is the instance that needs every part of the model at once.
#   T1 (entry {A}): e1: X -> Y ,  e2: Y -> X      target X
# Nothing produces X or Y from A: X only comes from e2, which needs Y, which only comes
# from e1, which needs X. Expected INFEASIBLE. It takes all three mechanisms:
#   * without support, marking everything and selecting nothing answers 0;
#   * support alone admits the cycle; the strictly descending times refute it, since
#     t_mk(X) = t_ev(e2) > t_mk(Y) = t_ev(e1) > t_mk(X);
#   * the entry exemption is what that descent bottoms out on -- take it away and every
#     instance, not just this one, becomes infeasible.
# ---------------------------------------------------------------------------------------
unfounded_cycle = Example(
    name="unfounded_cycle",
    problem=CompositionProblem(
        traces=(Trace("T1", ["A"], [Event("e1", ["X"], ["Y"]), Event("e2", ["Y"], ["X"])]),),
        target="X",
    ),
    expected=None,
    teaches="support kills marks-from-nothing; the descending times kill marks-from-a-cycle",
)

# ---------------------------------------------------------------------------------------
# Plain unreachability: nothing produces the target.
#   Goal wants mk[G]; support with no producer forces mk[G] = 0. INFEASIBLE.
# ---------------------------------------------------------------------------------------
unreachable_target = Example(
    name="unreachable_target",
    problem=CompositionProblem(
        traces=(Trace("T1", ["A"], [Event("e1", ["A"], ["B"])]),),
        target="G",
    ),
    expected=None,
    teaches="Goal plus support with no producer => mk[G]==1 and mk[G]==0 => INFEASIBLE",
)


harder_example = Example(
    name="harder_example",
    problem=CompositionProblem(
        traces=(
            Trace("T1", ["A"], [Event("a1", ["A"], ["X"]), Event("a2", ["P"], ["G"])]),
            Trace("T2", ["B"], [Event("b1", ["X"], ["Q"]), Event("b2", ["R"], ["S"]), Event("b3", ["A"], ["B"])]),
            Trace("T3", ["C"], [Event("c1", ["Q"], ["R"]), Event("c2", ["S"], ["P"])]),
        ),
        target="G",
    ),
    expected=6,
    teaches="A more complex composition problem with multiple traces and events",
)
            


ALL: tuple[Example, ...] = (
    single_step,
    composition_required,
    source_disjunction,
    trace_order_delay,
    fastest_producer,
    unfounded_cycle,
    unreachable_target,
    harder_example,
)

BY_NAME = {e.name: e for e in ALL}
