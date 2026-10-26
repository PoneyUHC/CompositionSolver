
from ortools.sat.python import cp_model

from composition_model.CompositionInstance import CompositionInstance
from composition_model.model.ModelOptions import ModelOptions
from composition_model.model.Solution import Solution
from composition_model.model.CompositionEncoding import CompositionEncoding
from composition_model.model.SolverProgress import SolverProgress


class CompositionSolver:

    @staticmethod
    def solve(problem: CompositionInstance, options: ModelOptions = ModelOptions()) -> Solution:
        """One solve. A FEASIBLE result means the time limit cut the search off before the
        count was proved minimal: the certificate is valid, just possibly not the smallest."""
        enc = CompositionEncoding(problem, options)
        solver = CompositionSolver._make_solver(options)
        status = solver.solve(enc.model, SolverProgress(enc, options) if options.show_progress else None)

        if solver.status_name(status) not in ("OPTIMAL", "FEASIBLE"):
            return Solution(solver.status_name(status), None, {}, {}, {}, {}, {}, {}, solver.wall_time)

        return CompositionSolver._get_solution(enc, solver, status)


    @staticmethod
    def _make_solver(options: ModelOptions) -> cp_model.CpSolver:
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = options.max_seconds
        solver.parameters.log_search_progress = options.log_search
        # CP-SAT runs a portfolio in parallel; fixing workers and seed keeps runs reproducible.
        solver.parameters.num_workers = options.num_workers
        solver.parameters.random_seed = options.random_seed
        # Presolve probing re-propagates every constraint once per literal, and TraceSwaps'
        # NoOverlap spans every event: on a few thousand events each probing pass costs tens
        # of seconds of wall time while barely registering in the deterministic time that
        # budgets presolve -- so it neither pays off nor stops in time. Off, the same answers
        # come back several times faster, small instances included.
        solver.parameters.cp_model_probing_level = 0
        return solver

    @staticmethod
    def _get_solution(enc: CompositionEncoding, solver: cp_model.CpSolver, status: int) -> Solution:
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

    @staticmethod
    def verify(
            solution: Solution,
            problem: CompositionInstance,
            options: ModelOptions = ModelOptions()
        ) -> list[str]:
            """Return the list of violated properties. Empty == the certificate is valid."""
            if not solution.ok:
                return ["no solution to verify"]

            v: list[str] = []
            mk, t_mk, sel, t_ev = solution.marked, solution.mark_time, solution.selected, solution.event_time

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
                independent = term.measure(problem, solution)
                if independent is None:
                    continue
                if solution.term_values.get(term.name) != independent:
                    v.append(
                        f"objective term {term.name}: solution says "
                        f"{solution.term_values.get(term.name)}, recomputing gives {independent}"
                    )
    
            return v

