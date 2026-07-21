# Composition-graph reachability with time — CP-SAT implementation

```
composition_model.py   domain + CP-SAT encoding + independent semantic verifier
oracle.py              brute-force reference implementation (no solver, different paradigm)
examples.py            7 minimal examples, each with a hand-derived optimum
random_problems.py     tiny random instance generator
test_reachability.py   7 tests: hand == CP-SAT == oracle, + property tests   ← the evidence
demo.py                cross-validation table + the composed traces
```

```bash
pip install ortools
python demo.py                # the demonstration
python test_reachability.py   # ≈3 s, incl. 300 randomized differential cases
```

---

## 1. The problem

A composition graph is a collection of **traces**. A trace is an ordered sequence of
**events** plus a set of **entry entities**. An event reads from **source** entities and can
produce **destination** entities. Given a **target** entity, find the earliest time it can
be reached by a trace composed out of the recorded traces — events may be taken from
different traces and interleaved, as long as each trace's own order is respected.

## 2. The model

With `T = |events|`:

| variable | domain | meaning |
|---|---|---|
| `sel[e]` | {0,1} | event `e` is selected into the composed trace |
| `t_ev[e]` | 0..T | the time `e` is scheduled at |
| `mk[x]` | {0,1} | entity `x` is marked: it supports a data flow from an entry point to the target |
| `t_mk[x]` | 0..T | the time `x` becomes marked |

```
(1) Entry                mk[x]                                        for x an entry point
(2) Justified selection  sel[e] ⇒ ⋁_{s ∈ src(e)} ( mk[s] ∧ t_mk[s] < t_ev[e] )
(3) Justified marking    mk[x]  ⇒ ⋁_{e : x ∈ dst(e)} ( sel[e] ∧ t_mk[x] = t_ev[e] )
                                                              for x NOT an entry point
(4) Trace order          i < j, same trace  ⇒  t_ev[e_i] < t_ev[e_j]
(5) Goal                 mk[target]
    Objective            min t_mk[target]
```

**Why it is correct.** (3) is a support constraint: a mark must have a cause. Without it,
marking every entity and selecting no event satisfies everything and answers 0 on any
instance. (2) and (3) together force every support chain to descend strictly in time, so
circular support (`X` marks `Y` marks `X`) is impossible. (1) is the base case that the
descent bottoms out on — which is why (3) is restricted to non-entry entities: demand that
entry points be produced too and the descent has no floor, making *every* instance
infeasible.

Support, the descending times, and the entry exemption are all three load-bearing.
`unfounded_cycle` in `examples.py` is the instance that needs each of them.

**Why `T = |events|` is enough.** Entries sit at time 0 and (2) is strict, so a selected
event has time ≥ 1, and one trace of `k ≤ |events|` events needs `k` strictly increasing
slots above 0. Tight when a single trace contains every event —
`test_max_time_bound_is_sufficient` builds that case.

---

## 3. Methodology

A solution here is not a number, it is a **certificate**: a proof that the target is
reachable, and it is machine-checkable. So the answer is computed **four independent ways**
and they are made to disagree if anything is wrong:

| # | Artifact | Paradigm | Catches |
|---|---|---|---|
| 1 | `examples.py` docstrings | hand derivation, written **before** running anything | "the solver agrees with itself" |
| 2 | `composition_model.solve` | CP-SAT | — |
| 3 | `oracle.brute_force_optimum` | exhaustive schedule enumeration + least fixpoint, no solver | over-constraining (wrong INFEASIBLE, wrong optimum) |
| 4 | `composition_model.verify` | re-reads the model constraint by constraint in pure Python | under-constraining (accepting nonsense) |

`test_randomized_differential_against_oracle` then runs 2 vs 3 vs 4 on 300 random tiny
instances, with a guard asserting the sample is not degenerate (15–85 % must be reachable,
or "they agree" is vacuous).

```
example                       hand      cp-sat      oracle   verifier  schedules
single_step                      1           1           1         OK          2
composition_required             3           3           3         OK         24
source_disjunction               1           1           1         OK          9
trace_order_delay                2           2           2         OK          4
fastest_producer                 1           1           1         OK         50
unfounded_cycle         INFEASIBLE  INFEASIBLE  INFEASIBLE        n/a          3
unreachable_target      INFEASIBLE  INFEASIBLE  INFEASIBLE        n/a          2
```

### Why the oracle is the right ground truth

Fix a schedule `t_ev` respecting trace order and take the least fixpoint

```
m(x) = 0                                                              x an entry point
m(d) = min { t_ev(e) | d ∈ dst(e), ∃ s ∈ src(e). m(s) < t_ev(e) }     otherwise
```

* **oracle ≤ CP.** By induction on `t_mk` in any certificate, `m(x) ≤ t_mk(x)`.
* **CP ≤ oracle.** From the fixpoint, build a certificate: for each `x` with `m(x) > 0`
  select the *earliest* enabling event `e_x` and set `marks_dst(e_x, x)` and
  `use_src(e_x, s)` for some `s` with `m(s) < t_ev(e_x)`.

The optima coincide, so a runtime disagreement means one of the two implementations is
wrong — on an instance of three events, which you can read end to end.

### The one modelling idea worth knowing

(2) and (3) are disjunctions of *conjunctions*. Rather than building that shape directly,
each disjunct gets a **witness literal** — `use_src[e][s]`, `marks_dst[e][d]` — which is the
solver's explicit choice of witness, and the conjunction hangs off it. Linear in the number
of pairs, propagates well, and it leaves the witness readable in the answer, so a solution
prints as a checkable certificate:

```
[composition_required] target = G
  t=1  T1[0]e1   enabled by [A]  ->  marks [X@1]
  t=2  T2[0]f1   enabled by [X]  ->  marks [Y@2]
  t=3  T1[1]e2   enabled by [Y]  ->  marks [G@3]
```

Note also that no big-M appears anywhere: CP-SAT has native strict inequality on integers.
That is the main reason to prefer it to a MILP here — no magic constant, better propagation.

---

## 4. Modelling decisions

* **Entity identity.** Entities are identified by name across traces: if two traces mention
  `X`, it is the same `X`. Entry points are declared per trace, but no constraint asks which
  trace an entry point came from, so they are used as a single union.
* **Entry points are marked at time 0.** The model only requires them *marked*. Pinning is
  optimum-neutral — their `t_mk` only ever appears on the small side of the `<` in (2), so 0
  dominates — but without it a solution may report an entry point "becoming marked" at
  time 3.
* **`t_mk` of an unmarked entity is meaningless** and is pinned to 0. Cannot change
  feasibility or the objective: every constraint reading `t_mk[x]` is guarded by a literal
  that also implies `mk[x]`.
* **Selection is free, so `sel` does not mean "useful".** Nothing forces an event to be
  selected, and nothing requires a selected event to mark anything — so among the
  optimal-time solutions there are certificates padded with events that mark nothing.
  `minimize_selected_events` (on by default) is a lexicographic *second* objective: phase 2
  re-solves with `t_mk[target]` **frozen** at the phase-1 optimum, so it cannot trade time
  for size; it only returns a minimal certificate.
  `test_tie_break_returns_a_minimal_certificate` exhibits both.
* **Trace order applies to every event of a trace, selected or not**, which implies
  `t_ev[e] ≥ index(e)`: an event cannot fire before its own prefix has consumed that many
  slots, even when the prefix is not selected. `trace_order_delay` is worth 2 rather than 1
  for exactly this reason.
* **`t_ev` is not globally injective.** Events from different traces may share a slot, which
  gives a synchronous-step semantics: everything marked at `t` is usable at `t+1`.

## 5. Scale

The examples are tiny so the oracle can check them exhaustively; the encoding is not.
Random instances, solved to proven optimality including the tie-break phase:

| events | entities | time |
|---|---|---|
| 70 | 60 | 0.2 s |
| 266 | 292 | 0.8 s |
| 953 | 978 | 3.7 s |
