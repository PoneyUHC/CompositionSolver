

import argparse

from composition_model.model.model_options import DEFAULT_MODEL_OPTIONS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Phase 1 parses a folder of trace JSON files and reports what is in "
        "them; phase 2 asks for one or more entry entities and a single goal, and solves "
        "for reachability."
    )
    parser.add_argument("folder", help="folder containing the trace collection")
    parser.add_argument(
        "--entries",
        action="append",
        default=[],
        metavar="ENTITY[,ENTITY...]",
        help="one or more normalized entity ids marked at t=0: comma-separate them "
        "(--entries a,b) or repeat the flag (--entries a --entries b).",
    )
    parser.add_argument(
        "--goal",
        metavar="ENTITY",
        help="the single normalized entity id to reach. Given together with --entries, "
        "phase 2 runs once from the command line instead of prompting.",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=DEFAULT_MODEL_OPTIONS.max_seconds,
        help="solver time limit in seconds (default: %(default)s)."
    )
    parser.add_argument(
        "--silent", action="store_true", help="do not print a line per improving solution"
    )
    return parser

