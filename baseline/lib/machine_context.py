"""Which machine is this drive running on, and what to do when that is not what it was last (DR256).

A mismatch is never a failure. The drive keeps a profile per machine it has run on; at boot the current machine is compared with them
and the result is a *state* that selects *behaviours*: record, adapt, check compatibility, or ask for help. Nothing here refuses to boot
or denies access. Work that cannot be settled deterministically is queued and only released after the substrate, GUI, browser, internet
and AI are up, because that is when there is something able to help.

States (assess):
    first_machine   no profile yet: this is the install host (or a drive that never recorded one). Record it.
    known           the fingerprint matches a profile. Nothing to do beyond noting the visit.
    changed         the same machine with parts changed (GPU, NIC, memory...): re-check what depends on those parts.
    new_machine     no profile matches: the drive moved. Build up as it discovers; verify data and caches against this machine.
    unreadable      the fingerprint could not be read: treated as unknown, retried later, never fatal.

Registry types (GLOBAL scope, so recovery can read them): `machine_profiles` (one per machine, keyed by its identifier) and
`adaptation_tasks` (one per pending piece of work).
"""
from __future__ import annotations

import hashlib
import time

import identifiers
import registry

PROFILES = "machine_profiles"
TASKS = "adaptation_tasks"
STAGES = ("substrate", "gui", "browser", "internet", "ai")        # readiness stages, in the order they come up
# fingerprint keys that say *which machine* (identity) versus parts that can change on the same machine (components)
IDENTITY_KEYS = ("system_uuid", "board_serial", "chassis_serial", "nic_macs")
COMPONENT_KEYS = ("cpu_model", "memory_gib", "gpus", "nics", "storage_controllers")
DMI_IDENTITY_KEYS = ("system_uuid", "board_serial", "chassis_serial")


class ContextError(ValueError):
    pass


def _registry():
    registry.register_type(PROFILES, "Machines this drive has run on, with their fingerprints (machine_context.py)",
                           default_scope=registry.GLOBAL)
    registry.register_type(TASKS, "Work pending because the drive moved or its machine changed (machine_context.py)",
                           default_scope=registry.GLOBAL)
    return registry


class FileReader:
    """`read(path)` and `listdir(path)` over real files below `root` (so recovery or a lab can point it at a mounted tree)."""
    def __init__(self, root: str = "/"):
        from pathlib import Path
        self._base = Path(root)

    def __call__(self, path):
        try:
            return (self._base / path.lstrip("/")).read_text()
        except OSError:
            return None

    def listdir(self, path):
        try:
            return sorted(p.name for p in (self._base / path.lstrip("/")).iterdir())
        except OSError:
            return []

    def isdir(self, path):
        return (self._base / path.lstrip("/")).is_dir()


def file_reader(root: str = "/"):
    return FileReader(root)


def _nic_macs(read) -> str | None:
    """MAC addresses of the physical wired NICs (a real device behind them; not bridges, wireless or virtual), sorted and joined."""
    listdir = getattr(read, "listdir", None)
    if listdir is None:
        return None
    macs = []
    for name in listdir("/sys/class/net"):
        base = f"/sys/class/net/{name}"
        if name == "lo" or not read.isdir(base + "/device") or read.isdir(base + "/bridge") or read.isdir(base + "/wireless"):
            continue
        mac = (read(base + "/address") or "").strip().lower()
        if mac and mac != "00:00:00:00:00:00":
            macs.append(mac)
    return ",".join(sorted(macs)) or None


def _cpu_model(text):
    for line in (text or "").splitlines():
        if line.lower().startswith("model name"):
            return line.split(":", 1)[1].strip()
    return None


def _memory_gib(text):
    for line in (text or "").splitlines():
        if line.startswith("MemTotal:"):
            return str(round(int(line.split()[1]) / 1024 / 1024))
    return None


def read_fingerprint(read, extra: dict | None = None) -> dict:
    """The current machine's fingerprint from `read(path) -> str | None` (sysfs/procfs, injected so tests and recovery can supply it).
    Anything unreadable is left out; identity keys present are enough to tell machines apart."""
    def get(path):
        try:
            value = read(path)
        except OSError:
            return None
        value = (value or "").strip()
        return value if value and value.lower() not in ("none", "default string", "to be filled by o.e.m.", "0") else None
    dmi = "/sys/class/dmi/id/"
    found = {"system_uuid": get(dmi + "product_uuid"), "board_serial": get(dmi + "board_serial"),
             "chassis_serial": get(dmi + "chassis_serial"), "board_name": get(dmi + "board_name"),
             "cpu_model": _cpu_model(read("/proc/cpuinfo")),
             "memory_gib": _memory_gib(read("/proc/meminfo"))}
    macs = _nic_macs(read)
    if macs:
        # With a firmware identity the NICs are just parts of this machine; without one (a VM, an unusual board) they are the identity.
        found["nics" if any(found.get(k) for k in DMI_IDENTITY_KEYS) else "nic_macs"] = macs
    found.update(extra or {})
    return {k: v for k, v in found.items() if v}


def _same_identity(a: dict, b: dict) -> bool:
    shared = [k for k in IDENTITY_KEYS if k in a and k in b]
    return bool(shared) and all(a[k] == b[k] for k in shared)


def assess(fingerprint: dict, profiles: dict) -> dict:
    """Pure. `profiles` maps profile id -> fingerprint. Returns {"state", "profile"} (the matching profile id, if any) and, for
    `changed`, which component keys differ."""
    if not any(k in fingerprint for k in IDENTITY_KEYS):
        return {"state": "unreadable", "profile": None}
    if not profiles:
        return {"state": "first_machine", "profile": None}
    for pid, known in sorted(profiles.items()):
        if _same_identity(fingerprint, known):
            differ = sorted(k for k in COMPONENT_KEYS if k in fingerprint and k in known and fingerprint[k] != known[k])
            return {"state": "changed" if differ else "known", "profile": pid, "differs": differ}
    return {"state": "new_machine", "profile": None}


# what each state asks for: (task kind, needs a helper because it cannot be settled deterministically, readiness stage it waits for)
BEHAVIOURS = {
    "first_machine": [],
    "known": [],
    "unreadable": [("retry-fingerprint", False, "substrate")],
    "changed": [("recheck-changed-parts", False, "substrate")],
    "new_machine": [
        ("discover-hardware", False, "substrate"),
        ("check-installer-cache", False, "substrate"),
        ("check-appdata", False, "substrate"),
        ("check-user-data", False, "substrate"),
        ("rebuild-vm-config", True, "ai"),
        ("resolve-incompatibilities", True, "ai"),
    ],
}


def _profile_id(host: str, fingerprint: dict) -> str:
    digest = hashlib.sha256("|".join(f"{k}={fingerprint.get(k, '')}" for k in IDENTITY_KEYS).encode()).hexdigest()[:20]
    return identifiers.map_external(host, "hardware", f"machine-{digest[:12]}", digest, scheme="dmi")


def load_profiles() -> dict:
    entries = _registry().list_entries(PROFILES, scope=registry.GLOBAL, read_only=True)
    return {pid: dict(e.get("attributes", {}).get("fingerprint", {})) for pid, e in entries.items()}


def observe(host: str, fingerprint: dict, *, now: float | None = None) -> dict:
    """Compare the current machine with the profiles, record the visit, queue the work the state asks for, and return the assessment
    with the queued task ids. Never raises for a mismatch; an unreadable fingerprint is a state, not an error."""
    reg = _registry()
    now = time.time() if now is None else now
    result = assess(fingerprint, load_profiles())
    state = result["state"]
    if state in ("first_machine", "new_machine"):
        pid = _profile_id(host, fingerprint)
        role = "installer_host" if state == "first_machine" else "adopted"
        reg.upsert_entry(PROFILES, pid, scope=registry.GLOBAL, value={"role": role},
                         attributes={"fingerprint": fingerprint, "role": role, "first_seen": now, "last_seen": now, "host": host})
        result["profile"] = pid
    elif state in ("known", "changed"):
        entry = reg.get_entry(PROFILES, result["profile"], scope=registry.GLOBAL)
        attrs = dict(entry.get("attributes", {}))
        attrs.update(last_seen=now, fingerprint=dict(attrs.get("fingerprint", {}), **fingerprint) if state == "changed" else attrs.get("fingerprint", {}))
        reg.upsert_entry(PROFILES, result["profile"], scope=registry.GLOBAL, value=entry.get("value"), attributes=attrs)
    result["tasks"] = [_queue(reg, host, result, kind, assist, stage, now, order)
                       for order, (kind, assist, stage) in enumerate(BEHAVIOURS[state])]
    return result


def _queue(reg, host, result, kind, assist, stage, now, order) -> str:
    task_id = f"{result['profile'] or 'unknown'}:{kind}"
    existing = reg.get_entry(TASKS, task_id, scope=registry.GLOBAL)
    if existing is None or existing.get("attributes", {}).get("status") == "done":
        reg.upsert_entry(TASKS, task_id, scope=registry.GLOBAL, value={"status": "pending"},
                         attributes={"kind": kind, "status": "pending", "needs_helper": assist, "waits_for": stage,
                                     "state": result["state"], "profile": result["profile"], "host": host, "queued": now, "order": order})
    return task_id


def due(ready: set | frozenset) -> list:
    """Pending tasks whose readiness stage is up, oldest first. A task that needs a helper is released only when *every* stage through `ai`
    is ready, because until then nothing able to help exists; a deterministic task needs only its own stage."""
    entries = _registry().list_entries(TASKS, scope=registry.GLOBAL, read_only=True)
    out = []
    for task_id, entry in entries.items():
        attrs = entry.get("attributes", {})
        if attrs.get("status") != "pending":
            continue
        needed = STAGES[: STAGES.index(attrs["waits_for"]) + 1]
        if attrs.get("needs_helper"):
            needed = STAGES
        if all(stage in ready for stage in needed):
            out.append(((attrs.get("queued", 0), attrs.get("order", 0)), task_id, attrs))
    return [(task_id, attrs) for _, task_id, attrs in sorted(out, key=lambda t: (t[0], t[1]))]


def complete(task_id: str, *, outcome: str = "done", detail: str = "") -> None:
    """Mark a task finished (`done`) or settled without changes (`not_needed`). Anything it could not settle stays pending: use `defer`."""
    _set_status(task_id, "done" if outcome in ("done", "not_needed") else outcome, detail)


def defer(task_id: str, detail: str) -> None:
    """The task could not be settled deterministically: keep it pending, flagged as needing a helper, with the reason."""
    reg = _registry()
    entry = reg.get_entry(TASKS, task_id, scope=registry.GLOBAL)
    if entry is None:
        raise ContextError(f"unknown task {task_id}")
    attrs = dict(entry.get("attributes", {}), needs_helper=True, waits_for="ai", detail=detail)
    reg.upsert_entry(TASKS, task_id, scope=registry.GLOBAL, value=entry.get("value"), attributes=attrs)


def _set_status(task_id, status, detail):
    reg = _registry()
    entry = reg.get_entry(TASKS, task_id, scope=registry.GLOBAL)
    if entry is None:
        raise ContextError(f"unknown task {task_id}")
    attrs = dict(entry.get("attributes", {}), status=status, detail=detail)
    reg.upsert_entry(TASKS, task_id, scope=registry.GLOBAL, value={"status": status}, attributes=attrs)
