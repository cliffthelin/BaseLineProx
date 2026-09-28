"""The real dependency-tracking and health-validation layer (decision
record 88, direct instruction): "A dependencies table needs to be in
place to record not just system field dependencies but install level
and probably other levels as we grow this. Those dependencies should
be predefined and validated before install begins and as health
validations both at boot and intervals and adhoc calls. Some values
will break things loudly some will break things silently."

Lives in the same primary Baseline database `settings_store.py` uses
(`settings_store.DEFAULT_DB_PATH`) - not a second database, per direct
instruction to build this "in that same DB" if one already exists.
Two tables: `dependencies` (the real, queryable definitions - what is
in place, inspectable directly via sqlite3 even outside Python) and
`dependency_check_results` (every check ever run, so the most recent
result for any dependency is always available for troubleshooting -
"referenced in things like stack traces or determining the system
configuration").

**Loud vs silent (direct instruction)**: `severity` on each
`Dependency` is either `LOUD` (a failure here would visibly break
something - refuse to proceed) or `SILENT` (a failure here would NOT
announce itself - wrong config, degraded behavior, nothing crashes).
`run_checks` records both, but only a caller checking specifically for
LOUD failures should ever treat this as a reason to refuse; SILENT
failures are recorded for `dump_configuration_snapshot` and any
troubleshooting flow to surface, never used to block anything by
themselves - blocking on a failure nobody expected to be loud would
itself be a surprise.

**Extensibility ("probably other levels as we grow this")**: `level`
is an open string, not an enum - "system" and "install" are the real
levels this pass needs; `register_dependencies` lets any future module
add its own level (e.g. "persona", "app") without editing this file.
"""
from __future__ import annotations

import importlib
import json
import shutil
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

import settings_store

LOUD = "loud"
SILENT = "silent"
SEVERITIES = (LOUD, SILENT)

PRE_INSTALL = "pre_install"
BOOT = "boot"
INTERVAL = "interval"
ADHOC = "adhoc"
PHASES = (PRE_INSTALL, BOOT, INTERVAL, ADHOC)


@dataclass(frozen=True)
class Dependency:
    id: str
    level: str
    description: str
    severity: str
    phases: tuple
    check_kind: str
    check_args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CheckResult:
    id: str
    ok: bool
    detail: str
    severity: str
    level: str


# ---------------------------------------------------------------------------
# Check kinds - a small, real vocabulary covering this pass's actual
# dependencies without needing a bespoke Python function per id. A
# dependency too specific for any of these can still register its own
# `check_kind` via `register_check_kind` (e.g. GPG-chain verification,
# which already has a real, tested implementation elsewhere this
# module has no reason to duplicate).
# ---------------------------------------------------------------------------

def _check_binary_on_path(args: dict) -> tuple[bool, str]:
    name = args["name"]
    found = shutil.which(name)
    return (found is not None, f"{name!r} found at {found}" if found else f"{name!r} not found on PATH")


def _check_path_exists(args: dict) -> tuple[bool, str]:
    p = Path(args["path"])
    return (p.exists(), f"{p} exists" if p.exists() else f"{p} does not exist")


def _check_python_module_importable(args: dict) -> tuple[bool, str]:
    name = args["module"]
    try:
        importlib.import_module(name)
        return (True, f"{name!r} is importable")
    except ImportError as exc:
        return (False, f"{name!r} is not importable: {exc}")


def _check_setting_configured(args: dict) -> tuple[bool, str]:
    group, key = args["group"], args["key"]
    try:
        value = settings_store.get_setting(group, key)
    except KeyError:
        return (False, f"{group}.{key} is not a known setting")
    options = next((s.options for s in settings_store.settings_in_group(group) if s.key == key), None)
    if options is not None and value not in options:
        return (False, f"{group}.{key} = {value!r} is not one of its defined options {options!r}")
    return (True, f"{group}.{key} = {value!r}")


CHECK_KINDS: dict = {
    "binary_on_path": _check_binary_on_path,
    "path_exists": _check_path_exists,
    "python_module_importable": _check_python_module_importable,
    "setting_configured": _check_setting_configured,
}


def register_check_kind(name: str, fn) -> None:
    """`fn(check_args: dict) -> (ok: bool, detail: str)`. Refuses to
    silently shadow a built-in kind - a name collision here is a real
    bug in whichever caller registered second."""
    if name in CHECK_KINDS:
        raise ValueError(f"check kind {name!r} is already registered")
    CHECK_KINDS[name] = fn


# ---------------------------------------------------------------------------
# The real, concrete seed this pass needs. Grows via
# register_dependencies, matching settings_store.register_schema's own
# "don't make this file grow forever" precedent.
# ---------------------------------------------------------------------------
SEED_DEPENDENCIES = (
    Dependency(
        "system.sqlite3_importable", "system",
        "Python's sqlite3 module must be importable - every config/settings/dependency read or "
        "write in this codebase depends on it (decision record 87).",
        LOUD, (PRE_INSTALL, BOOT, INTERVAL, ADHOC),
        "python_module_importable", {"module": "sqlite3"},
    ),
    Dependency(
        "system.openssl_on_path", "system",
        "openssl must be on PATH - used for TLS cert generation (self_installer.py), password "
        "hashing (drive_setup_answer.py), and answer-server fingerprint pinning.",
        LOUD, (PRE_INSTALL, BOOT, INTERVAL, ADHOC),
        "binary_on_path", {"name": "openssl"},
    ),
    Dependency(
        "install.self_installer_lvm_preset_valid", "install",
        "self_installer.lvm_size_preset must currently resolve to one of LVM_SIZE_PRESETS - a "
        "stale/out-of-range stored value would otherwise only surface as a bare KeyError deep "
        "inside self_installer.py, a loud failure in the worst possible place to see one first.",
        LOUD, (PRE_INSTALL, ADHOC),
        "setting_configured", {"group": "self_installer", "key": "lvm_size_preset"},
    ),
    Dependency(
        "install.self_installer_fqdn_valid", "install",
        "self_installer.fqdn must currently resolve to one of its defined presets. A stale value "
        "here would not crash anything - the install would just complete with an unexpected "
        "hostname - the exact shape of a silent failure this table exists to catch.",
        SILENT, (PRE_INSTALL, ADHOC),
        "setting_configured", {"group": "self_installer", "key": "fqdn"},
    ),
)

_REGISTRY: list[Dependency] = list(SEED_DEPENDENCIES)


def register_dependencies(defs) -> None:
    existing = {d.id for d in _REGISTRY}
    for d in defs:
        if d.id in existing:
            raise ValueError(f"dependency {d.id!r} is already registered")
        _REGISTRY.append(d)
        existing.add(d.id)


def all_dependencies() -> list:
    return list(_REGISTRY)


def dependencies_at_level(level: str) -> list:
    return [d for d in _REGISTRY if d.level == level]


# ---------------------------------------------------------------------------
# Storage - same primary database settings_store.py uses, two new
# tables. No Runner injection, same reasoning as settings_store.py:
# sqlite3 is a stdlib embedded call, not an external-process boundary.
# ---------------------------------------------------------------------------

def _connect(path: str):
    import os
    import sqlite3
    if path != ":memory:":
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS dependencies ("
        "id TEXT PRIMARY KEY, level TEXT NOT NULL, description TEXT NOT NULL, "
        "severity TEXT NOT NULL, phases TEXT NOT NULL, check_kind TEXT NOT NULL, "
        "check_args TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS dependency_check_results ("
        "row_id INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL, phase TEXT NOT NULL, "
        "checked_at REAL NOT NULL, ok INTEGER NOT NULL, detail TEXT NOT NULL, "
        "severity TEXT NOT NULL, level TEXT NOT NULL)"
    )
    return conn


def sync_definitions(*, path: str | None = None) -> None:
    """Persists the current in-memory registry into the `dependencies`
    table - real, queryable "what is in place" even from outside
    Python (a plain `sqlite3` CLI against the primary Baseline
    database), not just whatever happens to be registered in the
    running process right now."""
    path = path if path is not None else settings_store.DEFAULT_DB_PATH
    with closing(_connect(path)) as conn:
        for d in _REGISTRY:
            conn.execute(
                "INSERT INTO dependencies (id, level, description, severity, phases, check_kind, check_args) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET level=excluded.level, description=excluded.description, "
                "severity=excluded.severity, phases=excluded.phases, check_kind=excluded.check_kind, "
                "check_args=excluded.check_args",
                (d.id, d.level, d.description, d.severity, json.dumps(d.phases), d.check_kind,
                 json.dumps(d.check_args)),
            )
        conn.commit()


def run_checks(*, phase: str, level: str | None = None, path: str | None = None) -> list:
    """Runs every registered dependency applicable to `phase` (and,
    optionally, restricted to one `level`), records each result, and
    returns the same results as real `CheckResult` objects. A broken
    check itself is recorded as a failure, never allowed to crash the
    whole run - one bad dependency must not blind every other check.

    Deliberately two passes, not one: a `check_kind` like
    `setting_configured` calls back into `settings_store`, which opens
    its own fresh connection to this same database file. Running
    checks *while* holding this function's own connection open with an
    uncommitted write transaction caused real `SQLITE_BUSY` lock
    contention against that nested connection - found as a real 10s+
    hang (two lock-wait timeouts back to back) in this module's own
    test suite, not a hypothetical. Every check now runs to completion
    with no database connection of this function's own open at all;
    only the second pass opens one, purely to persist already-computed
    results."""
    if phase not in PHASES:
        raise ValueError(f"unknown phase {phase!r} - must be one of {PHASES}")
    path = path if path is not None else settings_store.DEFAULT_DB_PATH
    sync_definitions(path=path)
    now = time.time()
    results: list = []
    for d in _REGISTRY:
        if phase not in d.phases or (level is not None and d.level != level):
            continue
        checker = CHECK_KINDS.get(d.check_kind)
        if checker is None:
            ok, detail = False, f"unknown check_kind {d.check_kind!r}"
        else:
            try:
                ok, detail = checker(d.check_args)
            except Exception as exc:  # noqa: BLE001 - one broken check must not crash the run
                ok, detail = False, f"check raised {exc!r}"
        results.append(CheckResult(d.id, ok, detail, d.severity, d.level))

    with closing(_connect(path)) as conn:
        for r in results:
            conn.execute(
                "INSERT INTO dependency_check_results (id, phase, checked_at, ok, detail, severity, level) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (r.id, phase, now, 1 if r.ok else 0, r.detail, r.severity, r.level),
            )
        conn.commit()
    return results


def latest_check_results(*, path: str | None = None) -> dict:
    """One entry per dependency id - its most recent result across any
    phase. What a troubleshooting dump or a stack-trace-adjacent
    diagnostic actually wants: not a whole history, just "what's true
    right now, as of the last time anything checked.\""""
    path = path if path is not None else settings_store.DEFAULT_DB_PATH
    with closing(_connect(path)) as conn:
        rows = conn.execute(
            "SELECT id, phase, checked_at, ok, detail, severity, level FROM dependency_check_results "
            "WHERE (id, checked_at) IN "
            "(SELECT id, MAX(checked_at) FROM dependency_check_results GROUP BY id)"
        ).fetchall()
    return {
        r[0]: {"phase": r[1], "checked_at": r[2], "ok": bool(r[3]), "detail": r[4],
               "severity": r[5], "level": r[6]}
        for r in rows
    }


def loud_failures(results) -> list:
    """The only real gate: a LOUD-severity dependency currently
    failing. A caller deciding whether to refuse to proceed (pre-
    install, most obviously) should check this, never the full result
    list - a SILENT failure is real and worth recording, but was never
    meant to block anything by itself."""
    return [r for r in results if not r.ok and r.severity == LOUD]


def dump_configuration_snapshot(*, path: str | None = None) -> dict:
    """A real, single-call diagnostic snapshot - "what is in place" for
    troubleshooting, meant to be referenced from a stack trace or an
    operator asking what's actually configured on this machine right
    now. Explicitly calls out any currently-failing SILENT dependency -
    by definition, nothing else would have surfaced it."""
    path = path if path is not None else settings_store.DEFAULT_DB_PATH
    results = latest_check_results(path=path)
    return {
        "settings": settings_store.all_effective_settings(path=path),
        "dependency_results": results,
        "silent_failures": [i for i, r in results.items() if not r["ok"] and r["severity"] == SILENT],
        "loud_failures": [i for i, r in results.items() if not r["ok"] and r["severity"] == LOUD],
    }


def main() -> int:
    """Thin CLI entry point for the interval timer
    (`baseline-dependency-check.timer`) - a plain, unconditional
    `adhoc`-shaped invocation would also use this module directly,
    this wrapper exists only for the periodic, unattended case."""
    results = run_checks(phase=INTERVAL)
    failed_loud = loud_failures(results)
    for r in results:
        status = "OK" if r.ok else ("LOUD-FAIL" if r.severity == LOUD else "silent-fail")
        print(f"[{status}] {r.id}: {r.detail}")
    return 1 if failed_loud else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
