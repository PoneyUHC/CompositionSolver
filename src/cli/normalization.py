"""
Entity identity: how a per-file "p:N" / "r:N" ref becomes a cross-trace `EntityId`.

"p:N"/"r:N" are *per-file* indices: r:19 in one file is unrelated to r:19 in another.
`composition_model` joins entities by name *across* traces, so refs must first be resolved
to a global identity. That resolution is delegated to a caller-supplied `normalize`
function, handed a `ResolvedRef` (kind, path/name, resource_type, pid, role). Its
contract: within a single trace it must map distinct refs to distinct ids -- two entities
of one trace must never collapse into one. `parse_trace` checks this and raises if it is
violated.

Pulling in the opposite direction is the need to join: ids must be the *same* across
traces wherever the entity is, or there is no composition to find. So the default
normalizer drops what is per-recording and keeps what is not. A resource keeps its path.
A std fifo loses the pid in "<proc>-<pid>-STDIN", so each process's stdin is one entity
across traces, and the shared comms fifos (fifo_router_to_access, ...) already join by
path -- exactly the cross-trace communication the composition model composes over.

That leaves the processes, where the two pulls collide: the trace files name all three
user processes "user", so the name is not injective, while the pid that would separate
them is different in every recording and would separate them everywhere. The way out is
to identify a process by the principal it acts for, which `roles_by_pid` reads off the
role-bearing fifos it talks on -- stable across recordings and meaningful to a reader.
"""

import re
from collections.abc import Callable

from composition_model.composition_types import EntityId


class ResolvedRef:
    """A `p:N` / `r:N` reference resolved against its file's process/resource tables.

    This is the object handed to a `Normalizer`. `kind` is "process" or "resource".
    Only the fields relevant to that kind are populated; the rest are None.
    """

    raw: str  # the original "p:N" / "r:N" ref
    kind: str  # "process" | "resource"
    name: str | None  # process name
    pid: int | None  # process pid
    path: str | None  # resource path
    resource_type: int | None  # resource type code
    role: str | None  # the principal this belongs to, when known (see `roles_by_pid`)

    def __init__(
        self,
        raw: str,
        kind: str,
        *,
        name: str | None = None,
        pid: int | None = None,
        path: str | None = None,
        resource_type: int | None = None,
        role: str | None = None,
    ) -> None:
        self.raw = raw
        self.kind = kind
        self.name = name
        self.pid = pid
        self.path = path
        self.resource_type = resource_type
        self.role = role

    def __repr__(self) -> str:
        return f"ResolvedRef({self.raw!r}, {self.kind!r})"


Normalizer = Callable[[ResolvedRef], EntityId]

# A convention of the recorded system, not of traces in general: the comms fifos name
# the principal at each end ("fifo_comm_to_u1", "fifo_u1_to_router").
_ROLE_FIFO_RE = re.compile(r"fifo_(?:comm|router)_to_(u1|u2|admin)$|fifo_(u1|u2|admin)_to_router$")


def roles_by_pid(data: dict) -> dict[int, str]:
    """pid -> the principal that process acts for ("u1", "u2", "admin"), where clear.

    The trace files give every user process the same name, "user", so the name alone
    cannot tell three distinct principals apart -- and pids cannot either, since they
    differ in every recording and so would stop entities joining across traces. What is
    both stable and meaningful is which role-bearing fifo a process talks on.

    A process is assigned a role only when it touches the fifos of exactly one: that is
    true of each `user` process, and deliberately not of `router`, which relays all
    three and keeps its own name. Processes touching none (auth, access) get no role.
    """
    resources = data.get("resources", [])
    processes = data.get("processes", [])
    touched: dict[int, set[str]] = {}
    for ev in data.get("events", []):
        proc = ev.get("process")
        if not isinstance(proc, str) or not proc.startswith("p:"):
            continue
        idx = int(proc[2:])
        for raw in (*ev.get("source_entities", ()), *ev.get("target_entities", ())):
            if not raw.startswith("r:"):
                continue
            m = _ROLE_FIFO_RE.search(resources[int(raw[2:])].get("path") or "")
            if m:
                touched.setdefault(idx, set()).add(m.group(1) or m.group(2))

    roles: dict[int, str] = {}
    for idx, found in touched.items():
        pid = processes[idx].get("pid")
        if len(found) == 1 and pid is not None:
            roles[pid] = next(iter(found))
    return roles


def default_normalizer(ref: ResolvedRef) -> EntityId:
    """Resource -> its path; process -> "proc:<role or name>".

    A std fifo is named "<proc>-<pid>-STDIN"; the pid is dropped so the fifo joins across
    traces, and the owner is named by role where it has one, since three processes share
    the name "user". That keeps every id unique within a file, as the injective-per-trace
    contract requires, while still joining shared entities across traces.
    """
    if ref.kind == "resource":
        if ref.resource_type == 0:
            name_parts = ref.path.split("-")
            if len(name_parts) == 3 and name_parts[2] in ("STDIN", "STDOUT", "STDERR"):
                return f"fifo:{ref.role or name_parts[0]}-{name_parts[2]}"
        return ref.path

    elif ref.kind == "process":
        return f"proc:{ref.role or ref.name}"
