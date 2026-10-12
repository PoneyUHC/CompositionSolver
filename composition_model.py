"""
Reachability across a composition graph, with time. CP-SAT encoding.

THE PROBLEM
-----------
A composition graph is a collection of traces. A trace is an ordered sequence of events
plus a set of entry entities. An event reads from source entities and can produce
destination entities. Given a target entity, find the *smallest* composed trace that
reaches it -- the fewest recorded events that together justify it. Events may be taken
from different traces and interleaved, as long as each trace's own order is respected.

Time is still in the model, as the constraint that makes composition meaningful (a cause
must precede its effect, and a trace's own order is fixed), but it is no longer what is
optimized. The answer to "by when" is `sol.mark_time[target]`: a time the target
demonstrably can be reached by, no longer the earliest such time.

THE MODEL
---------
    T = |events|

    sel[e]  in {0,1}    event e is selected into the composed trace
    t_ev[e] in 0..T     the time e is scheduled at
    mk[x]   in {0,1}    entity x is marked: it supports a data flow from an entry point
                        to the target
    t_mk[x] in 0..T     the time x becomes marked

    (1) Entry               mk[x]                                     for x an entry point
    (2) Justified selection sel[e] => OR_{s in src(e)} ( mk[s] and t_mk[s] < t_ev[e] )
    (3) Justified marking   mk[x]  => OR_{e : x in dst(e)} ( sel[e] and t_mk[x] = t_ev[e] )
                                                             for x NOT an entry point
    (4) Trace order         i < j and same trace  =>  t_ev[e_i] < t_ev[e_j]
    (5) Goal                mk[target]
        Objective           a list of terms, minimized lexicographically. The default
                            is (trace swaps, selected events) -- see DEFAULT_OBJECTIVE.

WHY IT IS CORRECT
-----------------
(3) is a support constraint: a mark must have a cause. Without it, marking every entity and
selecting no event satisfies everything and answers 0 on any instance.

It is also what gives the objective its teeth. Selecting an event is otherwise free --
nothing obliges a selected event to be useful -- so under an objective that ignores
selection, the optimal solutions include ones padded with events that do nothing at all.
Minimizing the count removes that freedom: every selected event has to earn its place in
a support chain, so a certificate holds exactly the events it needs and no others.

(2) and (3) together force every support chain to descend strictly in time, so circular
support (X marks Y marks X) is impossible. (1) is the base case that recursion bottoms out
on, which is why (3) is restricted to non-entry entities: demand that entry points be
produced too and the descent has no floor, making every instance infeasible.

Support, the descending times, and the entry exemption are all three load-bearing.
`unfounded_cycle` in examples.py is the instance that needs each of them.

T = |events| is enough: entries sit at time 0 and (2) is strict, so a selected event has
time >= 1, and one trace of k <= |events| events needs k strictly increasing slots above 0.
It is tight when a single trace contains every event.

TWO CANONICALISATIONS, both optimum-neutral, so that answers read sensibly:
  * entry points are marked at time 0. Their t_mk only ever appears on the small side of
    the `<` in (2), so 0 dominates; without pinning, a solution may report an entry point
    "becoming marked" at time 3.
  * t_mk of an unmarked entity is meaningless and pinned to 0. Every constraint reading
    t_mk[x] is guarded by a literal that also implies mk[x].

CP-SAT NOTES
------------
The model is declarative: finite-domain variables plus constraints, in any order. Nothing
executes until solve().
    new_bool_var(n) / new_int_var(lo, hi, n)   variables; domains must be finite
    ~b                       negation of a Bool: a literal, not a new variable
    add_bool_or([a, b, ~c])  the clause (a or b or not c)
    add_implication(p, q)    == add_bool_or([~p, q])
    add(expr).only_enforce_if(lit)   half-reification, lit => expr. One-directional: for
                             lit <=> expr you must also post the negation under ~lit.
    add(x < y)               native on integers (becomes x + 1 <= y). No big-M anywhere in
                             this model, which is the main reason to prefer CP-SAT to a
                             MILP here: no magic constant, and far better propagation.
    minimize(expr)           the objective, set once.

WITNESS LITERALS -- the one non-obvious idea here. (2) and (3) are disjunctions of
*conjunctions*. Do not try to build that shape directly. Introduce one Bool per pair:
    use_src[e][s]    "s is the source witness chosen for e"
    marks_dst[e][d]  "e is the event that marked d"
and hang the conjunction off it:
    sel[e]        => OR_s use_src[e][s]
    use_src[e][s] => sel[e] and mk[s] and t_mk[s] < t_ev[e]
This is linear in the number of pairs, propagates well, and leaves the witness readable in
the solution -- so an answer prints as a checkable certificate rather than a bare number.
"""

from __future__ import annotations

from itertools import combinations
from typing import Iterable, Optional

from ortools.sat.python import cp_model

EntityId = str


# =======================================================================================
# Domain. Plain Python: both the encoding and the brute-force oracle consume this.
# =======================================================================================


class Event:

    name: str
    sources: Iterable[EntityId]
    destinations: Iterable[EntityId]
    id: str

    
    def __init__(
        self,
        name: str,
        sources: Iterable[EntityId],
        destinations: Iterable[EntityId],
        id: str = "",
    ) -> None:
        self.name = name
        self.sources = frozenset(sources)
        self.destinations = frozenset(destinations)
        self.id = id

    def set_id(self, id: str) -> None:
        self.id = id


class Trace:
    name: str
    entry_entities: frozenset[EntityId]
    events: tuple[Event]

    def __init__(
            self, 
            name: str, 
            entry_entities: Iterable[EntityId], 
            events: Iterable[Event]
    ) -> None:
        self.name = name
        self.entry_entities = frozenset(entry_entities)
        self.events = tuple(events)
        for i, e in enumerate(self.events):
            e.set_id(f"{self.name}[{i}]{e.name}")



class CompositionProblem:
    """The composition graph plus the reachability question asked of it.

    Entities are identified by name across traces: if two traces mention "X", it is the
    same X. Entry points are per-trace, but nothing distinguishes where an entry point came
    from, so `entry_entities` is their union.
    """

    traces: tuple[Trace, ...]
    target: EntityId

    # derived in __init__, never passed by the caller
    events: tuple[Event, ...]  # each stamped with a context-unique id
    entities: tuple[EntityId, ...]
    entry_entities: frozenset[EntityId]
    producers: dict[EntityId, tuple[Event, ...]]  # x -> events that can mark x
    _events_by_trace: dict[str, tuple[Event, ...]]

    def __init__(self, traces: tuple[Trace, ...], target: EntityId) -> None:
        self.traces = tuple(traces)
        self.target = target
        # Events already carry context-unique ids, stamped by trace() at construction.
        self._events_by_trace = {tr.name: tr.events for tr in self.traces}
        self.events = tuple(ev for tr in self.traces for ev in tr.events)
        self.entry_entities = (
            frozenset().union(*(tr.entry_entities for tr in self.traces)) if self.traces else frozenset()
        )

        seen: dict[EntityId, None] = {}  # dict keeps insertion order -> deterministic output
        for x in sorted(self.entry_entities):
            seen.setdefault(x, None)
        for ev in self.events:
            for x in sorted(ev.sources) + sorted(ev.destinations):
                seen.setdefault(x, None)
        seen.setdefault(self.target, None)
        self.entities = tuple(seen)

        producers: dict[EntityId, list[Event]] = {x: [] for x in self.entities}
        for ev in self.events:
            for d in ev.destinations:
                producers[d].append(ev)
        self.producers = {x: tuple(v) for x, v in producers.items()}

        self.validate()

    @property
    def max_time(self) -> int:
        return len(self.events)

    def events_of(self, trace_name: str) -> tuple[Event, ...]:
        return self._events_by_trace[trace_name]

    def restricted_to(self, trace_names: Iterable[str]) -> "CompositionProblem":
        keep = set(trace_names)
        return CompositionProblem(tuple(t for t in self.traces if t.name in keep), self.target)

    def validate(self) -> None:
        names = [tr.name for tr in self.traces]
        assert len(names) == len(set(names)), f"duplicate trace names: {names}"
        ids = [e.id for e in self.events]
        assert len(ids) == len(set(ids)), f"duplicate event ids: {ids}"
        for e in self.events:
            # Empty source/destination sets make (2)/(3) empty disjunctions, i.e. false, so
            # such an event could never be selected. Legal, but always a mistake.
            assert e.sources, f"{e.id} has no source: it could never be selected"
            assert e.destinations, f"{e.id} has no destination: it could never mark anything"


# =======================================================================================
# Objective
# =======================================================================================
#
# The objective is a list of terms, minimized lexicographically: the first term matters
# most, and later ones only break its ties. ADDING A TERM: subclass `ObjectiveTerm`,
# implement `build` and `upper_bound`, and name it in `ModelOptions.objective`. Nothing
# else changes -- the weights, the solution's per-term report and the verifier's re-check
# all follow from the list.


class ObjectiveTerm:
    """One quantity to minimize.

    `build` returns the CP-SAT expression for it, and may post whatever helper variables
    and constraints it needs on the way. `upper_bound` is the largest value that
    expression can take; it is what lets `scalarize` weight the terms so that no gain in
    a later term can ever pay for a loss in an earlier one.
    """

    name: str = "term"

    def build(self, enc: "CpEncoding"):
        raise NotImplementedError

    def upper_bound(self, problem: CompositionProblem) -> int:
        raise NotImplementedError

    def measure(self, problem: CompositionProblem, sol: "Solution") -> Optional[int]:
        """The term's value, recomputed from a finished certificate in pure Python.

        Optional second opinion: `verify` calls it and rejects a solution whose reported
        value disagrees. Return None to opt out.
        """
        return None


class SelectedEvents(ObjectiveTerm):
    """How many events the certificate contains.

    Without this term selection is free -- nothing obliges a selected event to be useful
    -- so optimal solutions include ones padded with events that mark nothing at all.
    """

    name = "events"

    def build(self, enc: "CpEncoding"):
        v = enc.model.new_int_var(0, len(enc.problem.events), "n_selected")
        enc.model.add(v == sum(enc.sel.values()))
        return v

    def upper_bound(self, problem: CompositionProblem) -> int:
        return len(problem.events)

    def measure(self, problem: CompositionProblem, sol: "Solution") -> Optional[int]:
        return sum(1 for on in sol.selected.values() if on)


class GoalTime(ObjectiveTerm):
    """When the target gets marked: the objective this model originally minimized.

    Not in DEFAULT_OBJECTIVE, but kept here because "how early?" is the natural third
    question to ask, and because it is what makes this structure worth its weight --
    putting it first restores the old earliest-time semantics in one line, and putting it
    last breaks ties towards certificates that finish sooner.
    """

    name = "time"

    def build(self, enc: "CpEncoding"):
        return enc.t_mk[enc.problem.target]

    def upper_bound(self, problem: CompositionProblem) -> int:
        return problem.max_time

    def measure(self, problem: CompositionProblem, sol: "Solution") -> Optional[int]:
        return sol.mark_time[problem.target]


class TraceSwaps(ObjectiveTerm):
    """How many times the composed trace hands off from one trace to another: the number
    of adjacent pairs in it whose two events come from different traces.

    Minimizing it prefers certificates that stay inside one recording as long as they can,
    so the answer shows the fewest points where composition is actually doing work.

    Two things this term needs, both of which it posts itself:

    * A TOTAL ORDER on the composed trace. "Adjacent" is only meaningful if no two
      selected events share a time, and nothing else in the model forbids that -- (4)
      orders each trace internally, but events of different traces are free to be
      simultaneous. So this term requires selected events to have distinct times, which
      genuinely shrinks the feasible set: schedules that relied on simultaneity are gone,
      and a goal may become reachable only later than it was before.
    * POSITIONS. `rank[e]` counts the selected events strictly before e, which makes e and
      f adjacent exactly when rank[f] == rank[e] + 1. That costs a boolean per pair of
      events, so this term is quadratic in |events|: comfortable for collections of a few
      hundred events, not for thousands.

    Only one direction of the adjacency reification is posted. `swaps` is defined as
    (selected - 1) - (adjacent same-trace pairs), so the objective already pushes every
    `adj` literal as true as the ranks allow, and the other direction would be dead weight.
    """

    name = "swaps"

    def build(self, enc: "CpEncoding"):
        model, problem = enc.model, enc.problem
        events, n = problem.events, len(problem.events)
        sel, t_ev = enc.sel, enc.t_ev
        trace_of = {e.id: tr.name for tr in problem.traces for e in tr.events}
        index_of = {e.id: i for tr in problem.traces for i, e in enumerate(tr.events)}

        # lt[(x, y)]: a literal meaning "x and y are both selected, and x comes first".
        # None where that is impossible, so the sums below simply skip it.
        lt: dict[tuple[str, str], object] = {}
        for a, b in combinations(events, 2):
            both = model.new_bool_var(f"both[{a.id},{b.id}]")
            model.add_implication(both, sel[a.id])
            model.add_implication(both, sel[b.id])
            model.add_bool_or([~sel[a.id], ~sel[b.id], both])

            if trace_of[a.id] == trace_of[b.id]:
                # (4) already orders a trace strictly, so the order is known, not chosen.
                early, late = (a, b) if index_of[a.id] < index_of[b.id] else (b, a)
                lt[(early.id, late.id)] = both
                lt[(late.id, early.id)] = None
                continue

            # Different traces: the model lets them be simultaneous, which would leave
            # "adjacent" undefined, so pin an order whenever both are in the trace.
            model.add(t_ev[a.id] != t_ev[b.id]).only_enforce_if(both)
            ab = model.new_bool_var(f"a_first[{a.id},{b.id}]")
            model.add(t_ev[a.id] < t_ev[b.id]).only_enforce_if([both, ab])
            model.add(t_ev[b.id] < t_ev[a.id]).only_enforce_if([both, ~ab])
            for x, y, orientation in ((a, b, ab), (b, a, ~ab)):
                conj = model.new_bool_var(f"lt[{x.id},{y.id}]")
                model.add_implication(conj, both)
                model.add_implication(conj, orientation)
                model.add_bool_or([~both, ~orientation, conj])
                lt[(x.id, y.id)] = conj

        # rank[e] = how many selected events come before e, i.e. its position in the
        # composed trace. Two events are adjacent exactly when their ranks differ by one.
        rank = {e.id: model.new_int_var(0, n, f"rank[{e.id}]") for e in events}
        for e in events:
            earlier = [lt[(f.id, e.id)] for f in events if f.id != e.id and lt[(f.id, e.id)] is not None]
            model.add(rank[e.id] == sum(earlier)) if earlier else model.add(rank[e.id] == 0)

        # One literal per same-trace pair that could be adjacent. Half-reified: `swaps`
        # subtracts these, so the objective already drives each as true as ranks permit.
        adj = []
        for tr in problem.traces:
            evs = problem.events_of(tr.name)
            for i, a in enumerate(evs):
                for b in evs[i + 1 :]:
                    lit = model.new_bool_var(f"adj[{a.id},{b.id}]")
                    model.add_implication(lit, lt[(a.id, b.id)])
                    model.add(rank[b.id] == rank[a.id] + 1).only_enforce_if(lit)
                    adj.append(lit)

        n_sel = model.new_int_var(0, n, "n_selected_for_swaps")
        model.add(n_sel == sum(sel.values()))
        steps = model.new_int_var(0, max(n - 1, 0), "composed_steps")
        model.add_max_equality(steps, [n_sel - 1, 0])  # nothing selected => no adjacencies
        swaps = model.new_int_var(0, max(n - 1, 0), "trace_swaps")
        model.add(swaps == steps - sum(adj)) if adj else model.add(swaps == steps)
        return swaps

    def upper_bound(self, problem: CompositionProblem) -> int:
        return max(len(problem.events) - 1, 0)

    def measure(self, problem: CompositionProblem, sol: "Solution") -> Optional[int]:
        trace_of = {e.id: tr.name for tr in problem.traces for e in tr.events}
        order = [uid for _, uid in sol.composed_trace()]
        return sum(1 for a, b in zip(order, order[1:]) if trace_of[a] != trace_of[b])


# What gets minimized, most significant first. Change this list to change the question.
DEFAULT_OBJECTIVE: tuple[ObjectiveTerm, ...] = (TraceSwaps(), SelectedEvents())


def scalarize(enc: "CpEncoding", terms: Iterable[ObjectiveTerm]):
    """Fold the terms into the single expression CP-SAT minimizes, exactly lexicographically.

    Mixed radix, lowest priority first: a term's weight is the product of (upper bound + 1)
    over every term below it, which is strictly more than those terms can contribute in
    total. So improving them can never compensate one unit of it, and one solve returns the
    lexicographic optimum -- no freezing a first objective and re-solving.
    """
    weight, parts = 1, []
    for term in reversed(tuple(terms)):
        expr = term.build(enc)
        enc.term_expr[term.name] = expr
        parts.append(weight * expr)
        weight *= term.upper_bound(enc.problem) + 1
    return sum(parts), weight - 1  # the expression, and its own upper bound


# =======================================================================================
# Options
# =======================================================================================


class ModelOptions:
    objective: tuple[ObjectiveTerm, ...]
    """The terms to minimize, most significant first. See DEFAULT_OBJECTIVE."""

    max_seconds: float
    log_search: bool
    num_workers: int
    random_seed: int

    def __init__(
        self,
        objective: tuple[ObjectiveTerm, ...] = DEFAULT_OBJECTIVE,
        max_seconds: float = 120.0,
        log_search: bool = False,
        num_workers: int = 8,
        random_seed: int = 0,
    ) -> None:
        self.objective = tuple(objective)
        self.max_seconds = max_seconds
        self.log_search = log_search
        self.num_workers = num_workers
        self.random_seed = random_seed


# =======================================================================================
# Encoding
# =======================================================================================


class CpEncoding:
    """Builds the CP-SAT model. Variables are left public for inspection and testing."""

    def __init__(
        self,
        problem: CompositionProblem,
        options: ModelOptions = ModelOptions(),
    ) -> None:
        self.problem = problem
        self.options = options
        self.model = cp_model.CpModel()
        T = problem.max_time

        # ---- variables ----
        self.sel = {e.id: self.model.new_bool_var(f"sel[{e.id}]") for e in problem.events}
        self.t_ev = {e.id: self.model.new_int_var(0, T, f"t_ev[{e.id}]") for e in problem.events}
        self.mk = {x: self.model.new_bool_var(f"mk[{x}]") for x in problem.entities}
        self.t_mk = {x: self.model.new_int_var(0, T, f"t_mk[{x}]") for x in problem.entities}

        # Witness literals (see module docstring). marks_dst does double duty: it is both
        # "e is the event that marked d" and the disjunct of constraint (3).
        self.use_src = {
            e.id: {s: self.model.new_bool_var(f"use_src[{e.id},{s}]") for s in sorted(e.sources)}
            for e in problem.events
        }
        self.marks_dst = {
            e.id: {d: self.model.new_bool_var(f"marks_dst[{e.id},{d}]") for d in sorted(e.destinations)}
            for e in problem.events
        }

        # ---- (1) Entry ----
        for x in sorted(problem.entry_entities):
            self.model.add(self.mk[x] == 1)
            self.model.add(self.t_mk[x] == 0)  # canonicalisation, optimum-neutral

        # ---- (2) Justified selection ----
        # sel[e] => OR_s ( mk[s] and t_mk[s] < t_ev[e] )
        for e in problem.events:
            self.model.add_bool_or(list(self.use_src[e.id].values())).only_enforce_if(self.sel[e.id])
            for s, w in self.use_src[e.id].items():
                self.model.add_implication(w, self.sel[e.id])
                self.model.add_implication(w, self.mk[s])
                self.model.add(self.t_mk[s] < self.t_ev[e.id]).only_enforce_if(w)

        # ---- (3) Justified marking, for non-entry entities ----
        # mk[x] => OR_{e : x in dst(e)} ( sel[e] and t_mk[x] = t_ev[e] )
        for e in problem.events:
            for d, w in self.marks_dst[e.id].items():
                self.model.add_implication(w, self.sel[e.id])
                self.model.add_implication(w, self.mk[d])
                self.model.add(self.t_mk[d] == self.t_ev[e.id]).only_enforce_if(w)

        for x in problem.entities:
            if x in problem.entry_entities:
                continue  # base case: already marked by (1)
            causes = [self.marks_dst[e.id][x] for e in problem.producers[x]]
            if causes:
                self.model.add_bool_or(causes).only_enforce_if(self.mk[x])
            else:
                self.model.add(self.mk[x] == 0)  # nothing produces x, so x can never be marked
            # An entity is marked at ONE time, so among several possible producers only the
            # ones scheduled at t_mk[x] may claim it. The others simply do not mark it.

        # ---- (4) Trace order ----
        # Stated for every pair i < j, but `<` is transitive, so the consecutive pairs imply
        # the rest: O(k) constraints instead of O(k^2), and the solver derives the closure.
        # Note this orders ALL events of a trace, selected or not, which implies
        # t_ev[e] >= index(e): an event cannot fire before its own prefix has consumed that
        # many slots. See `trace_order_delay` in examples.py.
        for tr in problem.traces:
            evs = problem.events_of(tr.name)
            for a, b in zip(evs, evs[1:]):
                self.model.add(self.t_ev[a.id] < self.t_ev[b.id])

        # ---- (5) Goal ----
        self.model.add(self.mk[problem.target] == 1)

        # ---- unmarked entities have a meaningless time; pin it (optimum-neutral) ----
        for x in problem.entities:
            self.model.add(self.t_mk[x] == 0).only_enforce_if(~self.mk[x])

        # ---- objective ----
        # Whatever `options.objective` lists, folded into one lexicographic expression.
        # `term_expr` keeps each term's own expression so the solution can report them
        # separately -- the scalar CP-SAT minimizes is a mixed-radix number, not a
        # quantity anyone wants to read.
        self.term_expr: dict[str, object] = {}
        total, total_ub = scalarize(self, options.objective)
        self.objective_var = self.model.new_int_var(0, total_ub, "objective")
        self.model.add(self.objective_var == total)
        self.model.minimize(self.objective_var)


# =======================================================================================
# Solving
# =======================================================================================


class Solution:
    status: str  # OPTIMAL | FEASIBLE | INFEASIBLE | UNKNOWN
    objective: Optional[int]  # the scalarized value CP-SAT minimized (mixed radix)
    term_values: dict[str, int]  # per objective term, by name -- this is what to read
    selected: dict[str, bool]
    event_time: dict[str, int]
    marked: dict[EntityId, bool]
    mark_time: dict[EntityId, int]
    used_source: dict[str, list[EntityId]]  # witness sources, per selected event
    marked_dest: dict[str, list[EntityId]]  # entities actually marked, per selected event
    wall_time: float

    def __init__(
        self,
        status: str,
        objective: Optional[int],
        selected: dict[str, bool],
        event_time: dict[str, int],
        marked: dict[EntityId, bool],
        mark_time: dict[EntityId, int],
        used_source: dict[str, list[EntityId]],
        marked_dest: dict[str, list[EntityId]],
        wall_time: float = 0.0,
        term_values: Optional[dict[str, int]] = None,
    ) -> None:
        self.status = status
        self.objective = objective
        self.selected = selected
        self.event_time = event_time
        self.marked = marked
        self.mark_time = mark_time
        self.used_source = used_source
        self.marked_dest = marked_dest
        self.wall_time = wall_time
        self.term_values = term_values or {}

    @property
    def ok(self) -> bool:
        return self.status in ("OPTIMAL", "FEASIBLE")

    def composed_trace(self) -> list[tuple[int, str]]:
        """The answer as a trace: selected events sorted by scheduled time."""
        return sorted((self.event_time[u], u) for u, s in self.selected.items() if s)


def solve(problem: CompositionProblem, options: ModelOptions = ModelOptions()) -> Solution:
    """One solve. A FEASIBLE result means the time limit cut the search off before the
    count was proved minimal: the certificate is valid, just possibly not the smallest."""
    enc = CpEncoding(problem, options)
    solver = _make_solver(options)
    status = solver.solve(enc.model)

    if solver.status_name(status) not in ("OPTIMAL", "FEASIBLE"):
        return Solution(solver.status_name(status), None, {}, {}, {}, {}, {}, {}, solver.wall_time)

    return _extract(problem, enc, solver, status)


def _make_solver(options: ModelOptions) -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = options.max_seconds
    solver.parameters.log_search_progress = options.log_search
    # CP-SAT runs a portfolio in parallel; fixing workers and seed keeps runs reproducible.
    solver.parameters.num_workers = options.num_workers
    solver.parameters.random_seed = options.random_seed
    return solver


def _extract(problem: CompositionProblem, enc: CpEncoding, solver: cp_model.CpSolver, status: int) -> Solution:
    sel = {u: solver.boolean_value(v) for u, v in enc.sel.items()}
    return Solution(
        status=solver.status_name(status),
        objective=solver.value(enc.objective_var),
        selected=sel,
        event_time={u: solver.value(v) for u, v in enc.t_ev.items()},
        marked={x: solver.boolean_value(v) for x, v in enc.mk.items()},
        mark_time={x: solver.value(v) for x, v in enc.t_mk.items()},
        used_source={u: [s for s, w in d.items() if solver.boolean_value(w)] for u, d in enc.use_src.items() if sel[u]},
        marked_dest={u: [d for d, w in ws.items() if solver.boolean_value(w)] for u, ws in enc.marks_dst.items() if sel[u]},
        term_values={name: solver.value(expr) for name, expr in enc.term_expr.items()},
        wall_time=solver.wall_time,
    )


# =======================================================================================
# Verifier
#
# Re-checks a returned assignment against the model, constraint by constraint, in pure
# Python. It shares no code with the encoding, so a mistranslation shows up here as a
# violation rather than as a plausible number.
# =======================================================================================


def verify(
    problem: CompositionProblem, sol: Solution, options: ModelOptions = ModelOptions()
) -> list[str]:
    """Return the list of violated properties. Empty == the certificate is valid."""
    if not sol.ok:
        return ["no solution to verify"]

    v: list[str] = []
    mk, t_mk, sel, t_ev = sol.marked, sol.mark_time, sol.selected, sol.event_time

    for x in sorted(problem.entry_entities):  # (1)
        if not mk[x]:
            v.append(f"(1) entry point {x} is not marked")
        if t_mk[x] != 0:
            v.append(f"(1) entry point {x} marked at {t_mk[x]} != 0")

    for e in problem.events:  # (2)
        if not sel[e.id]:
            continue
        if not any(mk[s] and t_mk[s] < t_ev[e.id] for s in e.sources):
            v.append(f"(2) selected {e.id}@{t_ev[e.id]} has no source marked strictly before it")

    for x in problem.entities:  # (3)
        if not mk[x] or x in problem.entry_entities:
            continue
        if not any(sel[e.id] and t_ev[e.id] == t_mk[x] for e in problem.producers[x]):
            v.append(f"(3) {x} marked at {t_mk[x]} but no selected event produces it then")

    for tr in problem.traces:  # (4)
        evs = problem.events_of(tr.name)
        for i in range(len(evs)):
            for j in range(i + 1, len(evs)):
                a, b = evs[i], evs[j]
                if not t_ev[a.id] < t_ev[b.id]:
                    v.append(f"(4) {a.id}@{t_ev[a.id]} !< {b.id}@{t_ev[b.id]}")

    if not mk[problem.target]:  # (5)
        v.append(f"(5) target {problem.target} is not marked")
    for term in options.objective:
        independent = term.measure(problem, sol)
        if independent is None:
            continue
        if sol.term_values.get(term.name) != independent:
            v.append(
                f"objective term {term.name}: solver says "
                f"{sol.term_values.get(term.name)}, recomputing gives {independent}"
            )

    return v
