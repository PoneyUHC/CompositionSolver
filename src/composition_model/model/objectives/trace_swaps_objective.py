
import itertools

from composition_model.composition_instance import CompositionInstance
from composition_model.model.composition_encoding import CompositionEncoding
from composition_model.model.objectives.objective import Objective
from composition_model.model.solution import Solution


class TraceSwapsObjective(Objective):
    """How many times the composed trace hands off from one trace to another: the number
    of adjacent pairs in it whose two events come from different traces.

    Minimizing it prefers certificates that stay inside one recording as long as they can,
    so the answer shows the fewest points where composition is actually doing work.

    COUNTING BLOCKS, NOT PAIRS. Cut the composed trace into blocks, maximal runs of
    consecutive events from one trace. Every hand-off ends a block, so

        swaps = blocks - 1        (0 when nothing is selected)

    and a block can be described one trace at a time, by looking only at neighbours in
    that trace's own order -- never at pairs of events from different traces. That is
    what keeps this term linear in |events|.

    For a trace with events e_1 < ... < e_k (selected or not):

        join[i]    the span from e_(i-1) to e_i lies inside one block of this trace.
                   join[i] => (sel[e_(i-1)] or join[i-1]) and (sel[e_i] or join[i+1]):
                   a chain of joins runs from one selected event to the next, with only
                   unselected events in between.
        start[i]   e_i opens a block:  start[i] <=> sel[e_i] and not join[i].
                   blocks = sum of start, so the objective pushes join as true as it can.

    What makes a join honest is that no selected event of ANOTHER trace may fall inside
    it. A block claims the time it spans, and one NoOverlap over every claim, from every
    trace, forbids two claims meeting:

        point[e]   [t_ev[e], t_ev[e] + 1), present when e is selected, or is an unselected
                   event sitting inside a block (the span after it is joined). Any event
                   of the trace, selected or not, can be what a foreign event lands on.
        gap[i]     [t_ev[e_(i-1)] + 1, t_ev[e_i]), present when join[i]: the open stretch
                   between two neighbours of the trace.

    A trace's own claims never collide -- its events have strictly increasing times, so
    points and gaps tile its time line in order. Between traces they collide exactly when
    a foreign selected event falls inside a block, or two selected events share a time.

    Two consequences, both deliberate:

    * A TOTAL ORDER on the composed trace. Selected events always claim a point, so no two
      share a time; "adjacent" is meaningless otherwise. This genuinely shrinks the
      feasible set: schedules that relied on simultaneity are gone, and a goal may become
      reachable only later than it was before.
    * Unselected events inside a block get a time of their own as well. This costs no
      certificate anything: with T = |events| there is a slot per event, so any total
      order of the selected events can be laid out with each trace's unselected events
      placed right after its preceding selected one, inside that block.

    `join` is the only real choice left: everything else is defined from it and from
    `sel`, which keeps the search from wandering through equivalent assignments.
    """

    name = "swaps"

    def build(self, enc: CompositionEncoding):
        model, problem, sel, t_ev = enc.model, enc.problem, enc.sel, enc.t_ev
        T = problem.max_time
        starts, claims = [], []

        for tr in problem.traces:
            evs = problem.events_of(tr.name)
            # join[i] for 1 <= i < k; None at both ends, where there is no span to join.
            join = [None] + [model.new_bool_var(f"join[{e.id}]") for e in evs[1:]] + [None]

            def either(lit, j):  # lit or join[j], skipping a join that does not exist
                return [lit] + ([join[j]] if join[j] is not None else [])

            for i, e in enumerate(evs):
                x = sel[e.id]
                if join[i] is None:
                    starts.append(x)  # first event of the trace: selected => opens a block
                else:
                    prev = evs[i - 1]
                    model.add_bool_or([~join[i]] + either(sel[prev.id], i - 1))
                    model.add_bool_or([~join[i]] + either(x, i + 1))
                    s = model.new_bool_var(f"start[{e.id}]")
                    model.add_bool_or([~x, join[i], s])
                    model.add_implication(s, x)
                    model.add_implication(s, ~join[i])
                    starts.append(s)
                    size = model.new_int_var(0, T, f"gap_size[{e.id}]")
                    claims.append(
                        model.new_optional_interval_var(t_ev[prev.id] + 1, size, t_ev[e.id], join[i], f"gap[{e.id}]")
                    )

                # e's own slot is taken when e is selected, or the span after it is joined.
                if join[i + 1] is not None:
                    busy = model.new_bool_var(f"busy[{e.id}]")
                    model.add_implication(x, busy)
                    model.add_implication(join[i + 1], busy)
                    model.add_bool_or([~busy, x, join[i + 1]])
                else:
                    busy = x
                claims.append(model.new_optional_fixed_size_interval_var(t_ev[e.id], 1, busy, f"point[{e.id}]"))

        model.add_no_overlap(claims)

        n = len(problem.events)
        blocks = model.new_int_var(0, n, "blocks")
        model.add(blocks == sum(starts))
        swaps = model.new_int_var(0, max(n - 1, 0), "trace_swaps")
        model.add_max_equality(swaps, [blocks - 1, 0])  # nothing selected => no hand-offs
        return swaps

    def upper_bound(self, problem: CompositionInstance) -> int:
        return max(len(problem.events) - 1, 0)

    def measure(self, problem: CompositionInstance, sol: Solution) -> int | None:
        trace_of = {e.id: tr.name for tr in problem.traces for e in tr.events}
        order = [uid for _, uid in sol.composed_trace()]
        return sum(1 for a, b in itertools.pairwise(order) if trace_of[a] != trace_of[b])
