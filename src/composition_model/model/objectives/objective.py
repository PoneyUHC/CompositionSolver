
from collections.abc import Iterable
from typing import Self

from composition_model.composition_instance import CompositionInstance
from composition_model.model.composition_encoding import CompositionEncoding
from composition_model.model.solution import Solution


class Objective:
    """One quantity to minimize.

    `build` returns the CP-SAT expression for it, and may post whatever helper variables
    and constraints it needs on the way. `upper_bound` is the largest value that
    expression can take; it is what lets `scalarize` weight the terms so that no gain in
    a later term can ever pay for a loss in an earlier one.
    """

    name: str = "term"

    def build(self, enc: CompositionEncoding):
        raise NotImplementedError

    def upper_bound(self, problem: CompositionInstance) -> int:
        raise NotImplementedError

    def measure(self, problem: CompositionInstance, sol: Solution) -> int | None:
        return None


    @staticmethod
    def scalarize(enc: CompositionEncoding, terms: Iterable[Self]):
        """Fold the objectives into the single expression CP-SAT minimizes, exactly lexicographically.

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