
import itertools

from ortools.sat.python import cp_model

from composition_model.composition_instance import CompositionInstance
from composition_model.model.model_options import DEFAULT_MODEL_OPTIONS, ModelOptions
from composition_model.model.objectives.objective import Objective


class CompositionEncoding:
    """Builds the CP-SAT model. Variables are left public for inspection and testing."""

    def __init__(
        self,
        problem: CompositionInstance,
        options: ModelOptions = DEFAULT_MODEL_OPTIONS,
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
            for a, b in itertools.pairwise(evs):
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
        total, total_ub = Objective.scalarize(self, options.objective)
        self.objective_var = self.model.new_int_var(0, total_ub, "objective")
        self.model.add(self.objective_var == total)
        self.model.minimize(self.objective_var)