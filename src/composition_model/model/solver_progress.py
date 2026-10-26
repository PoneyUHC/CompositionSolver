from __future__ import annotations

import sys
from typing import TYPE_CHECKING, TextIO

from ortools.sat.python import cp_model

if TYPE_CHECKING:
    from composition_model.model.composition_encoding import CompositionEncoding
    from composition_model.model.model_options import ModelOptions


class SolverProgress(cp_model.CpSolverSolutionCallback):
    """Prints one line per improving solution: time, the scalarized score, then each
    objective term's value in priority order.

    CP-SAT calls this from its worker threads, one call at a time, holding the GIL, so
    it must stay cheap: it only reads values the solver already has, never recomputes.
    """

    def __init__(self, enc: CompositionEncoding, options: ModelOptions, out: TextIO = sys.stdout) -> None:
        super().__init__()
        self._terms = [(t.name, enc.term_expr[t.name]) for t in options.objective]
        self._limit = options.max_seconds
        self._out = out

    def on_solution_callback(self) -> None:
        values = "  ".join(f"{name}={self.value(expr)}" for name, expr in self._terms)
        print(
            f"  {self.wall_time:5.1f}s / {self._limit:.0f}s  score={int(self.objective_value)}  {values}",
            file=self._out, flush=True,
        )
