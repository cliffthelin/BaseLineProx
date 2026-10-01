"""What the web application can run besides drive actions: ad hoc, in the background, or on a schedule.

Every operation checks `web_gate.require` itself (offdrive_backup does, and `execute` does), so none can run unless
the web application asked for it. A schedule is a record the web app signed when a logged-in session created it
(web_gate.sign_schedule); the scheduler runs only in the web service, verifies each record's signature before every
run, and ignores any record that was edited or never signed. There is no other way in: no script, no timer unit.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import offdrive_backup
import web_gate

MAX_SCHEDULES = 20

# An OPERATOR session (settings `access.operator_users`) may reach only these routes: run, schedule and watch
# operations. Everything else, including every drive action, settings, recovery and admin, is refused.
OPERATOR_PATHS = ("/operations", "/drive-admin/job-log", "/logout")


def operator_may_reach(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in OPERATOR_PATHS)


_BOT_OPERATION_PATHS = frozenset({"/operations", "/operations/run", "/operations/schedule", "/operations/schedule/remove",
                                  "/drive-admin/job-log", "/logout"})
_BOT_DRIVE_PATHS = frozenset({"/drive-admin", "/drive-admin/action", "/drive-admin/confirm", "/drive-admin/actions",
                              "/drive-admin/job-log", "/logout"})


def role_may_reach(role: str, path: str) -> bool:
    """Routes a limited login may reach. A bot role reaches only the pages its one action needs (never settings,
    recovery, standing approvals or operator accounts); which action it may ask for is enforced again by
    web_gate.role_permits and by the routes themselves."""
    if role == "admin":
        return True
    if role == "operator":
        return operator_may_reach(path)
    if isinstance(role, str) and role.startswith(web_gate.BOT_PREFIX):
        action = role[len(web_gate.BOT_PREFIX):]
        return path in (_BOT_OPERATION_PATHS if action in OPERATIONS else _BOT_DRIVE_PATHS)
    return False


@dataclass(frozen=True)
class Operation:
    op_id: str
    description: str
    params: dict            # name -> default (all bool)
    schedulable: bool


OPERATIONS = {
    "backup_offdrive": Operation(
        "backup_offdrive",
        "Add a verified, compressed backup set of everything on the SK hynix drives to the separate backup drive. "
        "Only ever adds files; deletes and overwrites nothing. `dry_run` checks and reports without writing; "
        "`force` skips the minimum interval between backups.",
        {"dry_run": False, "force": False}, True),
    "backup_guests": Operation(
        "backup_guests",
        "Add a new set holding a vzdump backup of each Proxmox VM and container that has a disk on the PC601's "
        "local-lvm (guests kept on the installer cache are already covered by the volume backup). Only ever adds "
        "files; deletes and overwrites nothing. `dry_run` lists what would be dumped without writing.",
        {"dry_run": False}, True),
    "backup_verify": Operation(
        "backup_verify",
        "Check the newest backup set on the backup drive: every archive against its checksum, and that "
        "changes-only sets still have the earlier sets they depend on. Read-only.",
        {}, True),
    "backup_test_restore": Operation(
        "backup_test_restore",
        "Prove the newest backup restores: rebuild its smallest archive into a temporary folder on this machine "
        "(never on the backup drive), check the files came back, then remove that temporary folder. Read-only on "
        "the backup drive.",
        {}, True),
    "backup_list": Operation(
        "backup_list", "List the backup sets on the backup drive. Read-only.", {}, False),
}


def validate(op_id: str, params: dict) -> dict:
    spec = OPERATIONS.get(op_id)
    if spec is None:
        raise ValueError(f"unknown operation {op_id!r}")
    if not isinstance(params, dict):
        raise ValueError("parameters must be an object")
    unknown = set(params) - set(spec.params)
    if unknown:
        raise ValueError(f"unknown parameter(s) for {op_id}: {', '.join(sorted(map(str, unknown)))}")
    clean = dict(spec.params)
    for name, value in params.items():
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be true or false")
        clean[name] = value
    return clean


def _destination(get_setting, run):
    import drive_admin
    destination = get_setting("backups", "offdrive_destination")
    if not destination:
        raise offdrive_backup.BackupError("no backup destination is configured (backups.offdrive_destination)")
    return offdrive_backup.resolve_destination(destination, run=run, allowed_serials=drive_admin.ALLOWED_TARGET_SERIALS,
                                               boot_serial=offdrive_backup._boot_serial())


def _verify_newest(origin, params, *, print_fn, get_setting, run) -> int:
    dest = _destination(get_setting, run)
    sets = offdrive_backup.list_sets(dest)
    if not sets:
        print_fn("[FAILED] there are no backup sets to verify")
        return 1
    newest = sets[0]
    offdrive_backup.verify_set(newest.path)
    offdrive_backup.verify_chain(dest, newest.name, deep=True)
    print_fn(f"[ok] {newest.name} verified: every archive matches its checksum and every set it depends on is intact")
    return 0


def _test_restore(origin, params, *, print_fn, get_setting, run) -> int:
    import shutil
    import tempfile
    dest = _destination(get_setting, run)
    sets = [s for s in offdrive_backup.list_sets(dest) if s.manifest.get("content", "volumes") != "guests"]
    if not sets:
        print_fn("[FAILED] there are no backup sets to test")
        return 1
    newest = sets[0]
    archives = newest.manifest.get("archives", [])
    if not archives:
        print_fn(f"[FAILED] {newest.name} lists no archives")
        return 1
    smallest = min(archives, key=lambda a: a.get("bytes", 0))
    label = smallest["name"].removesuffix(".tar.gz")
    scratch = tempfile.mkdtemp(prefix="baseline-test-restore-")
    try:
        offdrive_backup.restore_label(dest, newest.name, label, scratch)
        restored = sum(len(files) for _root, _dirs, files in os.walk(scratch))
        if restored == 0:
            print_fn(f"[FAILED] restoring {label} from {newest.name} produced no files")
            return 1
        print_fn(f"[ok] {newest.name}: {label} restored {restored} file(s) into a temporary folder, which was then removed")
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)          # only the folder this function just made


def _list_sets(origin, params, *, print_fn, get_setting, run) -> int:
    dest = _destination(get_setting, run)
    sets = offdrive_backup.list_sets(dest)
    for s in sets:
        archives = s.manifest.get("archives", [])
        print_fn(f"{s.name}: {len(archives)} archive(s), {sum(a.get('bytes', 0) for a in archives) / 2**30:.2f} GiB")
    print_fn(f"[ok] {len(sets)} backup set(s)")
    return 0


def execute(op_id: str, params: dict, origin, *, print_fn=print, get_setting=None, run=None, now=time.time) -> int:
    """Run one operation. Refuses (raises web_gate.NotFromWebApp) unless `origin` is a valid proof, signed by the
    web application, for exactly this operation and these parameters. Returns an exit code (0 = success)."""
    params = validate(op_id, params)
    web_gate.require(origin, op_id, params)
    if get_setting is None:
        import settings_store
        get_setting = settings_store.get_setting
    run = run or offdrive_backup._default_run
    try:
        if op_id == "backup_offdrive":
            return offdrive_backup.main(get_setting=get_setting, now=now, print_fn=print_fn, run=run,
                                        dry_run=params["dry_run"], force=params["force"], origin=origin)
        if op_id == "backup_guests":
            return offdrive_backup.main_guests(get_setting=get_setting, now=now, print_fn=print_fn, run=run,
                                               dry_run=params["dry_run"], origin=origin)
        if op_id == "backup_verify":
            return _verify_newest(origin, params, print_fn=print_fn, get_setting=get_setting, run=run)
        if op_id == "backup_test_restore":
            return _test_restore(origin, params, print_fn=print_fn, get_setting=get_setting, run=run)
        return _list_sets(origin, params, print_fn=print_fn, get_setting=get_setting, run=run)
    except offdrive_backup.BackupError as exc:
        print_fn(f"[FAILED] {exc}")
        return 1


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------

class ScheduleStore:
    """schedules.json: {"schedules": [signed records], "last_run": {op: epoch}}. Written atomically, mode 0600.
    `last_run` is not security-relevant (the worst a tamper does is run a signed schedule earlier or later)."""

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {"schedules": [], "last_run": {}}
        if not isinstance(data, dict) or not isinstance(data.get("schedules"), list):
            return {"schedules": [], "last_run": {}}
        if not isinstance(data.get("last_run"), dict):
            data["last_run"] = {}
        return data

    def save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, json.dumps(data, sort_keys=True).encode())
        finally:
            os.close(fd)
        os.replace(tmp, self.path)


class Scheduler:
    """Runs signed schedules. `run(op, params, origin)` is what executes one (the web service passes a function that
    starts a background job). The scheduler never runs anything whose signature does not verify."""

    def __init__(self, gate, store: ScheduleStore, run, clock=time.time):
        self.gate, self.store, self.run, self.clock = gate, store, run, clock
        self._thread = None
        self._stop = threading.Event()

    def set(self, sessions, token, op_id: str, params: dict, *, every_hours) -> dict:
        spec = OPERATIONS.get(op_id)
        if spec is None or not spec.schedulable:
            raise ValueError(f"{op_id!r} cannot be scheduled")
        params = validate(op_id, params)
        record = self.gate.sign_schedule(sessions, token, {"op": op_id, "params": params, "every_hours": every_hours},
                                         self.clock())
        with self.store._lock:
            data = self.store.load()
            others = [r for r in data["schedules"] if r.get("op") != op_id]
            if len(others) >= MAX_SCHEDULES:
                raise ValueError("too many schedules")
            data["schedules"] = others + [record]
            data["last_run"].pop(op_id, None)
            self.store.save(data)
        return record

    def remove(self, sessions, token, op_id: str) -> bool:
        self.gate._require_login(sessions, token, self.clock())
        with self.store._lock:
            data = self.store.load()
            kept = [r for r in data["schedules"] if r.get("op") != op_id]
            changed = len(kept) != len(data["schedules"])
            data["schedules"] = kept
            self.store.save(data)
        return changed

    def listing(self) -> list:
        out = []
        data = self.store.load()
        for record in data["schedules"]:
            try:
                self.gate.origin_for_schedule(record, self.clock())
                valid = True
            except web_gate.NotFromWebApp:
                valid = False
            out.append({"op": record.get("op"), "params": record.get("params"), "every_hours": record.get("every_hours"),
                        "last_run": data["last_run"].get(record.get("op")), "valid": valid})
        return [r for r in out if r["valid"]]

    def tick(self) -> None:
        now = self.clock()
        with self.store._lock:
            data = self.store.load()
            due = []
            for record in data["schedules"]:
                try:
                    origin = self.gate.origin_for_schedule(record, now)
                except (web_gate.NotFromWebApp, KeyError, TypeError):
                    continue
                last = data["last_run"].get(record["op"])
                if last is None or now - float(last) >= float(record["every_hours"]) * 3600:
                    data["last_run"][record["op"]] = now          # recorded before running: a failure cannot storm
                    due.append((record["op"], dict(record["params"]), origin))
            if due:
                self.store.save(data)
        for op, params, origin in due:
            try:
                self.run(op, params, origin)
            except Exception:  # noqa: BLE001 - one failing run must not stop the scheduler
                pass

    def start(self, interval_s: float = 60) -> None:
        if self._thread is not None:
            return

        def loop():
            while not self._stop.wait(interval_s):
                self.tick()
        self._thread = threading.Thread(target=loop, daemon=True, name="baseline-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
