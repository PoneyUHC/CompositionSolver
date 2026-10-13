# CLAUDE.md

Composition-graph reachability solved with CP-SAT (OR-Tools). Each trace is an ordered list of events (sources → destinations) plus entry entities. The task is to reach a target by interleaving events taken from several traces.

## Run (always use the venv; ortools 9.15, Python 3.12; pytest NOT installed)
- `venv/bin/python demo.py`: cross-validation table on `examples.ALL` (~1 s). It is the only end-to-end check that works right now.
- `venv/bin/python test_reachability.py`: **currently broken at import** (see Known state).
- `venv/bin/python trace_to_composition.py traces GOAL --no-entities --entry ID[,ID]`: runs non-interactively. **GOAL must come right after the folder**; putting it after the flags gives an argparse "unrecognized arguments" error. Without `--entry` and GOAL it blocks on `input()`, so pass both or append `< /dev/null`. IDs may be any substring that matches exactly one entity. To query a subset of recordings, copy them into a folder (there is no trace-subset flag).
- Put scratch scripts in the session scratchpad and do `sys.path.insert(0, repo)`.

## Files (find code by symbol, not line number)
- `composition_model.py` (~710 lines; sections are marked by `# ====` banners). It holds: domain (`Event`, `Trace`, `CompositionProblem`), objective (`ObjectiveTerm`, `SelectedEvents`, `GoalTime`, `TraceSwaps`, `DEFAULT_OBJECTIVE`, `scalarize`), `ModelOptions`, `CpEncoding`, `Solution`, `solve`, `_make_solver`, `_extract`, and `verify`. **Its module docstring and the `TraceSwaps` docstring are authoritative.** README.md is written for external readers (the recorded system, the scenarios, worked examples, caveats), not for developers. Its section 6 numbers come from real runs, so re-run them if the model changes.
- `trace_to_composition.py`: JSON traces become a `CompositionProblem`. Phase 1 is `parse_traces` + `TraceSurvey`; phase 2 is `build_problem`. Entity identity comes from `default_normalizer` and `roles_by_pid`. The CLI always uses `DEFAULT_OBJECTIVE` and only exposes `--max-seconds`.
- `examples.py`: `Example(name, problem, expected, teaches)`, plus `ALL` and `BY_NAME`. `expected` is the hand-derived **earliest time**. `ALL` includes `harder_example`, which has 43,904 oracle schedules.
- `oracle.py`: brute force without a solver. `brute_force_optimum` returns the **earliest time**; `closure` is the least fixpoint; `search_space_size` is also defined here.
- `random_problems.py`: tiny instance generator. Broken import, same cause as the tests.
- `traces/*.json`: 0.2–1 MB each. **Never cat them.** Use the survey instead: 8 files, 3470 events, 45 entities, 16 unproduced (the entry candidates). Entity IDs are absolute paths (`.../fs/policy`, `.../fs/user_1/file1`, `.../fs/comms/fifo_*`), `fifo:<role>-STD{IN,OUT,ERR}`, or `proc:<role|name>`. Roles are `u1`, `u2`, `admin`, `router`, `auth`, and `access`.

## Model invariants (don't break)
- Variables: `sel[e]`, `t_ev[e]`, `mk[x]` and `t_mk[x]` over 0..T with T=|events|. Witness literals `use_src[e][s]` and `marks_dst[e][d]` encode the disjunctions of conjunctions. No big-M; strict `<` is native.
- The three load-bearing pieces are: support (3) applies only to non-entry entities, (2)+(3) force times to descend strictly, and entry points are pinned at t=0. `unfounded_cycle` exercises all three.
- Trace order (4) applies to **all** events of a trace, selected or not. It is posted on consecutive pairs only.
- The objective is a lexicographic tuple folded by `scalarize` (mixed radix built from `upper_bound`). To add a term, subclass `ObjectiveTerm`; it needs `build`, `upper_bound`, and optionally `measure` for `verify`.
- `TraceSwaps` is **linear**: it counts blocks, not pairs, and `swaps = max(blocks-1, 0)`. It never compares events of different traces directly; keep it that way.
  - Per trace there is `join[i]`, one per consecutive pair, which is the only free choice. There is also `start[i] <=> sel and not join`.
  - Optional intervals `point[e]` (present if selected or inside a block) and `gap[i]` (present if `join[i]`) all go into **one** `add_no_overlap` across every trace.
  - Consequences: selected events form a total order, which shrinks the feasible set (no simultaneity), and unselected events inside a block take a slot too.
- `_make_solver` sets `cp_model_probing_level = 0` on purpose, because probing over the global NoOverlap is very slow. Don't re-enable it.
- `verify` must share **no code** with `CpEncoding`. Every new constraint must also be re-checked in `verify`, and in the oracle if the semantics change.
- `ModelOptions()` is a default argument, so it is evaluated once at import. Never compute machine-dependent values in its `__init__` defaults.
- `Trace.__init__` stamps `Event.id` on shared `Event` objects (`"{trace}[{i}]{name}"`).

## Known state (as of 2026-10-13, HEAD `poly swaps`)
- `test_reachability.py` and `random_problems.py` still import the removed `event`/`trace` helpers. They also use removed APIs: `ModelOptions(minimize_selected_events=)`, `CpEncoding(freeze_objective_at=, secondary=)`, and `solve().objective` read as a time. They need porting before they can count as evidence.
- `solve().objective` is now the mixed-radix scalar. Read the per-term values from `sol.term_values[name]` and the time from `sol.mark_time[target]`.
- In ortools 9.15, `model.Proto()` is a pybind object with no `ByteSize()`; use `len(model.Proto().constraints)`.

## Measured performance (ortools 9.15, 12 cores, 15 GB RAM, linear `TraceSwaps`)
- Full `traces/` collection, entry set = all 16 unproduced entities, `DEFAULT_OBJECTIVE`:
  - Build: 0.3 s, +32 MB, 80k constraints.
  - Solve: about 30 s to OPTIMAL, with peak RSS around +0.8–0.9 GB during the solve.
  - Goals `fs/policy` and `user_2/file2` both gave `events=2, swaps=0`, and the verifier passed. These answers are trivial because the shared libraries mark every process at once.
- Entry = `fifo:u2-STDIN` only:
  - `policy` and `file1` on all 8 traces: UNKNOWN at 120 s.
  - On 2 traces (user2 + admin_changes_policy, or user2 + user1_tries_access_with_success): FEASIBLE at 120 s with `events=6, swaps=1`.
  - `file1` on user2 alone: INFEASIBLE in 0.0 s. `password`: INFEASIBLE, since nothing produces it.
- CP-SAT facts that still hold:
  - Its `max_memory_in_mb` parameter is documented as pure-SAT only, so don't rely on it.
  - `solver.solve` releases the GIL, so a watchdog thread can call `solver.stop_search()`. I measured a ~5 s delay during presolve, but that was on the old quadratic model with probing on.
  - Freed model memory is not returned to the OS. `ctypes.CDLL("libc.so.6").malloc_trim(0)` returns it.

## Open work: RAM limit for the resolution (requested 2026-10-12, interrupted, nothing implemented)
The request was driven by the old O(n²) `TraceSwaps`, which needed about 15 GB for the full collection. Peak memory is now under 1 GB, so **ask the user whether it is still wanted** before building it.

If it is: add `ModelOptions.max_memory_mb` (None means auto; `inf` means off) and a watchdog thread that calls `stop_search` once `/proc/self/statm` RSS goes over the limit. Return a `"MEMORY_LIMIT"` status, call `malloc_trim` after each solve (the interactive CLI asks several questions in one process), and add a `--max-memory-mb` CLI flag. Delete this section once it is done.

## Style
- Plain classes with class-level annotations and an explicit `__init__` (no dataclasses), and `from __future__ import annotations`.
- CP-SAT snake_case API: `new_bool_var`, `add_implication`, `.only_enforce_if`, `new_optional_interval_var`.
- Comments and docstrings are dense and explain *why* and which invariant something relies on. Match that density.
- Commit messages are short and lowercase (e.g. `poly swaps`).
