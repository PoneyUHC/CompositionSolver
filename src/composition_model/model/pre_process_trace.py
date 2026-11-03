
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from composition_model.model.composition_encoding import CompositionEncoding  # noqa: TC004


from composition_model.composition_instance import CompositionInstance
from composition_model.composition_types import EntityId, Event, Trace
from composition_model.model.solution import Solution


def useful_sources(e: Event) -> frozenset[EntityId]:
    """The sources e can fire from and still mark something.

    Firing from s means s is marked strictly before e, so e can no longer mark s: if s is
    e's only destination, that firing marks nothing and is never needed.
    """
    return frozenset(s for s in e.sources if not e.destinations <= {s})


def useful_destinations(e: Event) -> frozenset[EntityId]:
    """The destinations e can actually mark: d is out when it is e's only source, since
    then d is marked strictly before e fires."""
    return frozenset(d for d in e.destinations if not e.sources <= {d})


class ShrunkInstance(CompositionInstance):
    """`original` with fewer events to encode, and the same answers.

    Three reductions, each dropping only events or witnesses that mark nothing. Every
    objective term is no worse without them (fewer events, fewer traces, no extra swap,
    no later mark), so the optimum is unchanged.

    * USELESS WITNESSES. Each kept event carries only its `useful_sources` and
      `useful_destinations`, so the encoding creates no use_src/marks_dst literal that
      could never mark anything.
    * DEAD EVENTS. An event with no useful source (equivalently, no useful destination)
      can never mark anything: it is dropped.
    * RUNS. Consecutive events of a trace with the same useful sources and destinations
      are interchangeable. Once one fires, every later copy finds its destinations
      already marked, so at most one copy per run is ever useful. A run is encoded as one
      kept event, which stands for whichever copy fires. A dead event ends a run.

    Dropped events still take their slot of the original trace, otherwise goals would be
    reached earlier than they can be: `max_time` stays the original horizon and
    `add_run_offsets` puts the slots back as offsets on the trace order. `expand` turns a
    solution of this instance into one of `original`, which `verify` checks as usual.
    """

    original: CompositionInstance
    runs: dict[str, tuple[Event, ...]]  # kept event id -> the original events it stands for
    dead_before: dict[str, int]  # kept event id -> dead events between it and the previous kept one
    dead_after: dict[str, int]  # trace name -> dead events after its last kept one

    def __init__(self, original: CompositionInstance) -> None:
        self.original = original
        self.runs, self.dead_before, self.dead_after = {}, {}, {}
        traces = []
        for tr in original.traces:
            kept: list[Event] = []
            runs: list[list[Event]] = []
            gaps: list[int] = []
            dead = 0  # dead events since the last kept one
            for e in tr.events:
                srcs, dsts = useful_sources(e), useful_destinations(e)
                if not srcs or not dsts:
                    dead += 1
                elif kept and not dead and (srcs, dsts) == (kept[-1].sources, kept[-1].destinations):
                    runs[-1].append(e)
                else:
                    kept.append(Event(e.name, srcs, dsts))
                    runs.append([e])
                    gaps.append(dead)
                    dead = 0
            shrunk = Trace(tr.name, kept)  # stamps the kept events' ids
            for k, run, gap in zip(shrunk.events, runs, gaps, strict=True):
                self.runs[k.id] = tuple(run)
                self.dead_before[k.id] = gap
            self.dead_after[tr.name] = dead
            traces.append(shrunk)
        super().__init__(tuple(traces), original.target, entry_entities=original.entry_entities)

    @property
    def max_time(self) -> int:
        return self.original.max_time  # every dropped event still needs its slot

    def add_run_offsets(self, enc: CompositionEncoding) -> None:
        """Trace order (4) as the original trace has it, run copies and dead events included.

        A run of k copies takes k consecutive slots of its trace, and the copy that fires
        can be any of them. With `start` the slot of the first copy, `t` the kept event's
        time and `gap` the dead events before the next run:

            start <= t                        the copies before the firing one fit after start
            next_start >= t + 1 + gap         the copies after it, then the dead events, fit
            next_start >= start + k + gap     before the next run starts

        Exact: given these, put as many copies as fit before t, and the rest right after
        it (`expand` does exactly this). With k = 1, start is t itself. All bounds are
        posted even when they repeat the encoding's t_prev < t or are trivially true;
        presolve drops those.
        """
        model, T = enc.model, self.max_time
        for tr in self.traces:
            prev = None  # (t, start, k) of the previous run
            for e in self.events_of(tr.name):
                t, k, gap = enc.t_ev[e.id], len(self.runs[e.id]), self.dead_before[e.id]
                start = t if k == 1 else model.new_int_var(0, T, f"run_start[{e.id}]")
                if k > 1:
                    model.add(start <= t)
                if prev is None:
                    model.add(start >= gap)
                else:
                    prev_t, prev_start, prev_k = prev
                    model.add(start >= prev_t + 1 + gap)
                    model.add(start >= prev_start + prev_k + gap)
                prev = (t, start, k)

            if prev is not None:  # the last run, then the trailing dead events, end by T
                last = T - self.dead_after[tr.name]
                prev_t, prev_start, prev_k = prev
                model.add(prev_t <= last)
                model.add(prev_start + prev_k - 1 <= last)

    def expand(self, sol: Solution) -> Solution:
        """`sol`, found on this instance, as a solution of `original`.

        Walking each original trace, every copy and dead event takes the next free slot,
        except the copy that fires, which takes the kept event's time. Copies go before it
        while they fit, the rest right after it. `add_run_offsets` guarantees there is
        room. Entities only dead events mention can never be marked, so they come back
        unmarked.
        """
        if not sol.ok:
            return sol
        kept_of = {c.id: k for k, run in self.runs.items() for c in run}
        selected: dict[str, bool] = {}
        event_time: dict[str, int] = {}
        fired: dict[str, str] = {}  # kept event id -> id of the original copy that fires
        for tr in self.original.traces:
            slot = 0  # first free slot of this trace
            for e in tr.events:
                if e.id in event_time:
                    continue  # a copy, already placed with its run
                if e.id not in kept_of:  # dead
                    selected[e.id], event_time[e.id] = False, slot
                    slot += 1
                    continue
                k = kept_of[e.id]
                run, t = self.runs[k], sol.event_time[k]
                before = min(len(run) - 1, t - slot)  # copies that go before the firing one
                for j, c in enumerate(run):
                    event_time[c.id] = slot + j if j < before else t + j - before
                    selected[c.id] = j == before and sol.selected[k]
                fired[k] = run[before].id
                slot = event_time[run[-1].id] + 1

        return Solution(
            status=sol.status,
            objective=sol.objective,
            selected=selected,
            event_time=event_time,
            marked={x: sol.marked.get(x, False) for x in self.original.entities},
            mark_time={x: sol.mark_time.get(x, 0) for x in self.original.entities},
            used_source={fired[k]: v for k, v in sol.used_source.items()},
            marked_dest={fired[k]: v for k, v in sol.marked_dest.items()},
            wall_time=sol.wall_time,
            term_values=sol.term_values,
        )
