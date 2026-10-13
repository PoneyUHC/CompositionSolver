# Trace composition: finding data flows that no single recording shows

This project takes several **recordings of a running system** and asks whether data could travel from one place to another by **chaining behaviours seen in different recordings**.

For example: *could what user 2 types at their keyboard end up influencing the system's access policy file?*

The answer is either a **proof that it cannot happen**, or a **step-by-step chain of recorded events** that you can read and check yourself.

The recordings come from a small multi-process file-access service. They were captured at the system-call level by the ProvScopeObserver provenance recorder. The reasoning is done by a constraint solver (Google OR-Tools CP-SAT). Every answer is checked a second time by an independent verifier before it is shown.

---

## 1. Why compose recordings?

A recording shows **one run** of a system: who opened what, who read from where, who wrote to where. Studied alone, a recording only tells you what happened in that run. Many questions, especially security ones, are about what **could** happen:

> Can an adversary who controls *this* input influence *that* resource?

Often no single recording contains the full path. Yet the system has been *seen* doing each part of it:

- in one run, a process receives data that came from the adversary;
- in another run, the same process writes to a sensitive file.

Neither run is alarming alone. Together, they describe a path the system might take.

This project treats the recordings as a **catalogue of behaviours the system is known to exhibit**. It asks whether some of those behaviours, taken in a consistent order, chain together from a starting point to a target. Such a chain is a **composed trace**. Composition is the point of the project: on the toy example below, and on real questions about the recorded system, the target is reachable *only* by combining recordings.

---

## 2. The recorded system

The recordings come from a small service with six processes that talk to each other through named pipes (FIFOs):

```
   user 1 ──┐                         ┌── auth     checks passwords (fs/misc/password)
            │                         │            and records who is logged in (fs/misc/allow)
   user 2 ──┼──────── router ─────────┤
            │   (relays every request │
   admin  ──┘    and every answer)    └── access   checks the policy (fs/policy), then reads or
                                                   writes the users' files
                                                   (fs/user_1/file1, fs/user_2/file2, fs/policy)

   every line is a pair of pipes, one in each direction
```

The three client programs (user 1, user 2, admin) take commands on their keyboard input and forward them to the router:

| command | what happens |
|---|---|
| `AUTH <password>` | the router asks **auth**, which checks the password file and answers `AUTH_OK` or `AUTH_ERROR` |
| `WRITE <file> <content>` | if the client is logged in, the router asks **access**, which checks the policy and writes the file (`WRITE_OK`), or refuses (`ACCESS_ERR_NOT_ALLOWED`) |
| `READ <file>` | same as `WRITE`, but **access** reads the file and sends its content back |
| anything else | the router answers `ERR_UNKNOWN_CMD` |

### The eight recordings

Each recording (`traces/*.json`) is one run of the whole service, playing one scenario:

| recording | scenario | events |
|---|---|---:|
| `user_authenticates_0` | user 1 logs in | 201 |
| `user1_tries_access_with_failed_auth_0` | user 1 gives a wrong password, then tries to write `file1`: refused, not logged in | 277 |
| `user1_tries_access_with_success_auth_0` | user 1 logs in and writes `Hello_from_1` to `file1` | 596 |
| `user1_read_existing_file_succeed_0` | user 1 logs in, writes `file1`, then reads it back | 718 |
| `user2_tries_access_with_success_auth_0` | user 2 logs in and writes `Hello_from_2` to `file2` | 596 |
| `access_write_denied_user1_0` | user 1 logs in and tries a path-traversal write to `../user_2/file1`: refused by the policy | 375 |
| `admin_changes_policy_0` | the admin logs in and overwrites the policy file with `TRASH_POLICY` | 561 |
| `malformed_message_0` | user 1 sends an unknown command: rejected by the router | 146 |
| | **total** | **3470** |

The recorder captures four kinds of system call for every process: **open**, **read**, **write** and **close**. Each recorded event names the process that performed it, the entities it read from (its *sources*), and the entities it affected (its *destinations*). Program start-up is captured too, for example every process opening the C library. The eight recordings mention **45 distinct entities** in total: processes, files, pipes and terminals.

---

## 3. From recordings to a composition graph

**Entities** are the things data can live in: the six processes, the files, the pipes between processes, and each process's terminal (keyboard input, screen output, error output).

**Events** are the recorded system calls. Each one carries data from its sources to its destinations, following the recorder's own declaration of what each call reads and affects. For instance:

- "access writes to fd 6" has the access process as its source and the policy file as its destination;
- "router finishes reading from fd 9" has the user-2 → router pipe as its source and the router as its destination.

**The same entity across recordings.** Composition only makes sense if "the router" in one recording is recognized as the router in another. That isn't automatic: process ids change from run to run, and the three client programs all have the same name (`user`). So entities are given stable identities:

- **files and pipes** are identified by their path;
- **processes** are identified by their role (`u1`, `u2`, `admin`, `router`, `auth`, `access`). A client's role is worked out from which pipes it talks on;
- **terminals** are identified by their owner's role, so `fifo:u2-STDIN` is user 2's keyboard input in every recording.

**Order within a recording is kept.** Events are kept in the order they were recorded. Events from *different* recordings have no fixed order relative to each other.

---

## 4. Asking a question

A question has two parts:

- **Entry points**: what is available for free at the start. Typically this is what an adversary controls, for example user 2's keyboard input.
- **A target**: the entity we want to know about, for example the policy file.

A **composed trace** is a sequence of recorded events, possibly from several recordings, that obeys four rules:

1. **Cause before effect.** An event can be used only if at least one of its sources has already been reached, *strictly earlier*.
2. **Effects are immediate.** Using an event reaches its destinations at that moment.
3. **Each recording keeps its order.** Two events from the same recording appear in their recorded order. Events from different recordings can be interleaved freely.
4. **Nothing from nothing.** Every reached entity other than an entry point must have been reached by an event in the trace. Circular reasoning ("X reached Y, which reached X") is impossible, because every step must come strictly later than what enabled it.

### What the answer looks like

- **"Unreachable"** is a proof: no ordering of the recorded behaviours obeying these rules gets from the entry points to the target.
- **"Reachable"** comes with a **certificate**: the composed trace itself, listing each step's recorded event, what enabled it, and what it reached. Anyone can check it by hand against the four rules. The tool also checks it automatically (section 7).

### Which chain, if there are several?

There are usually many valid chains. The tool prefers, in order:

1. **the fewest hand-offs between recordings**, that is, the chain that stays inside one recording as long as it can, so that the places where composition is doing the work stand out;
2. **then the fewest events**, so the certificate contains only steps that matter.

Each step also gets a **time slot** (`t=…`). Slots only order the steps; they are not clock times. The slot reported for the target is one at which the target *can* be reached, not necessarily the earliest possible.

---

## 5. A toy example

The smallest case where composition matters (`composition_required` in `examples.py`):

```
recording T1   entry point A     e1: A → X        e2: Y → G
recording T2                     f1: X → Y
target G
```

- **T1 alone** cannot reach G: `e2` needs Y, and nothing in T1 produces Y.
- **T2 alone** cannot either: `f1` needs X, and nothing in T2 produces X.
- **Composed:**

```
t=1  T1  e1   enabled by A  →  reaches X
t=2  T2  f1   enabled by X  →  reaches Y
t=3  T1  e2   enabled by Y  →  reaches G
```

T1's own order (`e1` before `e2`) is respected, with T2's event slotted in between.

---

## 6. Questions about the real recordings

All three questions below start from a single entry point: **user 2's keyboard input** (`fifo:u2-STDIN`).

### Can user 2's input reach the access policy?

Asked of two recordings, user 2's session and the admin's policy change, the tool returns a verified chain of **6 events with 1 hand-off**:

| step | recording | recorded event | enabled by | reaches |
|---|---|---|---|---|
| 1 | user 2's session | user 2's program opens its keyboard input | user 2's keyboard input | user 2's program |
| 2 | user 2's session | user 2 writes `AUTH user2_is_better` to its pipe to the router | user 2's program | user 2 → router pipe |
| 3 | user 2's session | the router reads from that pipe | user 2 → router pipe | the router |
| 4 | user 2's session | the router forwards `2 WRITE file2 Hello_from_2` to access | the router | router → access pipe |
| 5 | user 2's session | access reads that request | router → access pipe | access |
| | | *hand-off* | | |
| 6 | admin's session | access writes `TRASH_POLICY` into the policy file | access | **the policy file** |

In user 2's session, the access process received data derived from user 2's input. In the admin's session, the access process wrote the policy. Neither recording connects user 2 to the policy; together, they do.

### Can user 2's input reach user 1's file?

- **With user 2's session alone: unreachable**, proved in a fraction of a second.
- **With user 2's session plus user 1's successful write session: reachable**, again in 6 events with 1 hand-off. Data goes from user 2's program to the router, then into the response pipe between access and the router. In user 1's session, access then touches that pipe and writes `file1`.

### Can user 2's input reach the password file?

**Unreachable, even with all eight recordings.** No recorded event ever writes the password file, so no composition can reach it.

---

## 7. How to read the results

**"Reachable" is a candidate, not a confirmed attack.** The analysis is deliberately an over-approximation:

- **It tracks who touched what, not why.** Once a process has received data, everything it does afterwards counts as influenced by that data. It doesn't see message contents or the checks the processes make. In the policy example, access wrote the policy *because the admin was logged in*; the analysis only sees that access, which had earlier received user 2's data, later wrote the policy.
- **Behaviours from different runs are assumed able to happen in one run**, and a role (such as "the access process") is treated as the same entity in every recording.
- **It follows the recorder's view of each system call.** For instance, reading from a pipe also counts as affecting the pipe, and opening a file counts as receiving data from it.

So a reachable answer marks a flow worth inspecting. The certificate tells you exactly where to look.

**"Unreachable" is a strong statement**, within what was recorded: no combination of the observed behaviours connects the two entities. It says nothing about behaviours that were never recorded.

**The choice of entry points matters a lot.** At start-up, every process opens the same shared system libraries (`/etc/ld.so.cache`, `libc.so.6`). Give those for free, and every process is reached in a single step, so almost every target becomes trivially reachable. The tool lists the entities that no recorded event produces. These can only be entry points; they are not a recommended entry set.

**Solver status.** Each answer comes with one of four statuses:

| status | meaning |
|---|---|
| `OPTIMAL` | a verified chain, proved to be the best by the preferences of section 4 |
| `FEASIBLE` | a verified chain, but the time limit ran out before it could be proved the best |
| `INFEASIBLE` | unreachable, proved |
| `UNKNOWN` | the time limit ran out with no answer either way |

The examples in section 6 were obtained within the default 2-minute limit. The first two are `FEASIBLE`: their chains are valid and verified, but not proved minimal. Asked of all eight recordings at once, the same two questions come back `UNKNOWN` within 2 minutes, whereas narrowing to the relevant recordings gives an answer. Simple questions on the full collection, for example with a broad entry set, are solved to `OPTIMAL` in about 30 seconds.

---

## 8. How the answers are checked

An answer here is a proof, so the project computes it in **four independent ways** and checks that they agree:

| # | source | how it works | what it catches |
|---|---|---|---|
| 1 | hand derivations (`examples.py`) | the expected answer is worked out on paper and written down before anything runs | the solver agreeing with itself |
| 2 | the solver (`composition_model.py`) | constraint programming with OR-Tools CP-SAT | n/a: this is the answer under test |
| 3 | brute force (`oracle.py`) | tries every possible ordering, without any solver; feasible only on tiny cases | the solver missing answers |
| 4 | the verifier (`composition_model.verify`) | re-checks the returned chain against every rule, in plain Python, sharing no code with the solver | the solver accepting nonsense |

The verifier runs on **every** answer the command-line tool prints, including the ones in section 6.

`python demo.py` prints the cross-check on the hand-made examples. Each example isolates one aspect of the rules. In the output, the hand derivation and the brute force compute the **earliest possible time** of the target; the solver reports its chain's size (`cp events`) and time (`cp t`), which can never beat that earliest time.

```
example                  hand t  oracle t  cp events   cp t   verifier
single_step                   1         1          1      1         OK
composition_required          3         3          3      3         OK
source_disjunction            1         1          1      1         OK
trace_order_delay             2         2          1      2         OK
fastest_producer              1         1          1      1         OK
unfounded_cycle      INFEASIBLE INFEASIBLE INFEASIBLE INFEASIBLE   n/a
unreachable_target   INFEASIBLE INFEASIBLE INFEASIBLE INFEASIBLE   n/a
harder_example                6         6          6      6         OK
```

---

## 9. Running it

**Requirements:** Python 3.12 (tested) and OR-Tools.

```bash
pip install ortools==9.15.6755
```

`requirements.txt` is the author's full research environment. It includes many unrelated packages and a git-over-SSH reference to the ProvScopeObserver recorder, none of which this project needs.

**The demonstration** runs in about a second:

```bash
python demo.py
```

**Asking questions of the recordings.** The tool first prints a survey: the recordings, their sizes, every entity, and the entities nothing produces. It then prompts for entry points and a target:

```bash
python trace_to_composition.py traces
```

Or ask one question directly. The **target must come right after the folder**, before the options:

```bash
python trace_to_composition.py traces policy --entry u2-STDIN
```

- Entity names are long absolute paths, so any fragment that matches exactly one entity is accepted (`policy`, `file1`, `u2-STDIN`). Repeat `--entry`, or separate names with commas, to give several entry points.
- `--no-entities` shortens the survey.
- `--max-seconds N` changes the solver's time limit (default 120).

**Asking a question of only some recordings.** Copy those files into a folder of their own and point the tool at it:

```bash
mkdir subset
cp traces/user2_tries_access_with_success_auth_0.json traces/admin_changes_policy_0.json subset/
python trace_to_composition.py subset policy --entry u2-STDIN
```

This reproduces the first example of section 6 in about two minutes.

---

## 10. Repository contents

| file | role |
|---|---|
| `trace_to_composition.py` | reads the recordings, gives entities their cross-recording identity, and runs the command-line tool |
| `composition_model.py` | the reasoning: the rules of section 4 as a constraint model, the preferences, and the independent verifier. Its opening comment is the formal description of the model. |
| `examples.py` | small hand-solved examples, one aspect of the rules each |
| `oracle.py` | the brute-force cross-check |
| `demo.py` | the cross-check table and the toy example's certificates |
| `random_problems.py`, `test_reachability.py` | randomized and property tests (see below) |
| `traces/` | the eight recordings |

## 11. Status and limitations

- **Tests.** `test_reachability.py` and `random_problems.py` were written for an earlier version of the model, which looked for the earliest time rather than the fewest hand-offs. They do not run at the moment. `demo.py` is the working end-to-end check.
- **Scale.** The model grows linearly with the number of recorded events: the full collection of 3470 events is built in a fraction of a second. Solving time depends on the question. Long chains across many recordings can exceed the default time limit (section 7).
- **Scope.** Answers are only as complete as the recordings. A flow through behaviour that was never recorded can't be found, and a found flow is a candidate to inspect (section 7).

## License

GNU General Public License v3.0. See `LICENSE`.
