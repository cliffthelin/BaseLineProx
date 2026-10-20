"""Recovery mode itself (work-queue item 26, decision record 81) -
real entry, a discovery view (behind a login and the recovery credential), and the hard exit condition.
Explicitly NOT blocked on the withdrawn USB challenge-response
mechanism (decision record 77): every credential tier this module
touches comes from `recovery_tiers.py`/`admin_elevation.py` alone,
exactly per the direct instruction that closed that question ("We
decided not to do the usb recovery option").

**Real entry**: `should_enter` is the pure predicate - true either when
the discovery+repair cascade (`persist_bind_mounts.ensure_user_volume_mounted`'s
own already-real fallback chain) has genuinely exhausted itself, or on
a deliberate operator request ("on-demand"). `persist_bind_mounts.main`
calls `record_entry` directly when its own cascade fails, so entering
recovery mode is a real, durable fact the moment the condition that
requires it actually happens - not something a separate poller has to
notice later.

**Discovery**: `discover` reads only real mount state (which personas have
a volume actually present, which is currently active) and needs no
credential *of its own*. The web layer will not call it until the caller
has logged in and then proven this machine's root password or passphrase
(`recovery_tiers.RECOVERY_ACTIONS`); there is no unauthenticated access to it.

**Hard exit condition**: `can_exit`/`attempt_exit` refuse to consider
the machine able to leave recovery mode until at least one real
persona volume is confirmed mounted *read-write*
(`persist_bind_mounts.is_mounted_read_write`, not just "mounted at
all" - a corrupted volume can mount read-only) - per direct
instruction: "Without it being in read and write mode the machine
should not be able to leave recovery mode."

**SESSION_TEMP-scoped working state**: `record_entry`/`record_exit`
write to a small JSON file under SESSION_TEMP - the one volume this
project's own persona model designates for ephemeral, non-persistent
session data (per direct instruction: "the Temp volume can hold
session only user non persistent data and that is a fit for
recovery") - never under a persona's own persistence, which may be
exactly what is broken.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from repair import RealRunner, Runner


STATE_PATH = "/mnt/SESSION_TEMP/recovery_mode/state.json"


@dataclass
class DiscoveryReport:
    personas_found: list
    personas_missing: list
    active_persona: str | None


@dataclass
class ApplyResult:
    applied: bool
    detail: str


class RecoveryStateObservationError(RuntimeError):
    """Recovery state is present but cannot be trusted or inspected."""


def should_enter(cascade_applied: bool) -> bool:
    """The real entry predicate for the automatic half: true exactly
    when the discovery+repair cascade did NOT succeed - never
    triggered by anything less than a genuine, already-real failure."""
    return not cascade_applied


def discover(runner: Runner, *, personas: tuple,
             mount_table_path: str = "/proc/self/mounts") -> DiscoveryReport:
    """Reports which
    personas have a real, currently-mounted persistence volume and
    which don't, plus whichever persona is currently marked active
    (may be None if nothing is mounted at all)."""
    import persist_bind_mounts as pbm
    found = []
    missing = []
    for persona in personas:
        mountpoint = pbm.user_mountpoint_for(persona)
        if pbm.is_mounted(runner, mountpoint, mount_table_path=mount_table_path):
            found.append(persona)
        else:
            missing.append(persona)
    active = pbm.get_active_persona(runner) if found else None
    return DiscoveryReport(personas_found=found, personas_missing=missing, active_persona=active)


def can_exit(runner: Runner, *, personas: tuple,
             mount_table_path: str = "/proc/self/mounts") -> tuple[bool, str]:
    """The hard exit condition: at least one real persona volume
    confirmed mounted read-write. Checked directly against the kernel's
    own reported mount options, never inferred from "is it mounted at
    all" - a real corrupted volume can mount successfully but
    read-only, which must NOT count as satisfying this condition."""
    import persist_bind_mounts as pbm
    for persona in personas:
        mountpoint = pbm.user_mountpoint_for(persona)
        if pbm.is_mounted_read_write(runner, mountpoint, mount_table_path=mount_table_path):
            return True, f"persona {persona!r} confirmed read-write at {mountpoint}"
    return False, "no persona volume is confirmed read-write yet - cannot leave recovery mode"


def read_state(runner: Runner, *, state_path: str = STATE_PATH) -> dict | None:
    try:
        content = runner.read_text(state_path)
    except FileNotFoundError:
        return None
    except Exception as exc:
        raise RecoveryStateObservationError(
            f"cannot inspect recovery state at {state_path}: {exc}") from exc
    try:
        state = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise RecoveryStateObservationError(
            f"recovery state at {state_path} is invalid JSON: {exc}") from exc
    if not isinstance(state, dict) or type(state.get("active")) is not bool:
        raise RecoveryStateObservationError(
            f"recovery state at {state_path} must be an object with a boolean active field")
    return state


def _write_state(runner: Runner, state: dict) -> None:
    runner.makedirs(STATE_PATH.rsplit("/", 1)[0])
    runner.write_text_atomic(STATE_PATH, json.dumps(state, indent=2))


def record_entry(runner: Runner, *, now: float, reason: str) -> None:
    """`reason` is `"cascade_failed"` (real automatic entry, called
    directly by `persist_bind_mounts.main` on a genuine cascade
    failure) or `"on_demand"` (a deliberate operator request) - never
    inferred, always stated by the caller."""
    _write_state(runner, {"active": True, "reason": reason, "entered_at": now, "exited_at": None})


def is_active(runner: Runner, *, state_path: str = STATE_PATH) -> bool:
    state = read_state(runner, state_path=state_path)
    return bool(state and state.get("active"))


def attempt_exit(runner: Runner, *, personas: tuple, now: float,
                 mount_table_path: str = "/proc/self/mounts",
                 state_path: str = STATE_PATH) -> ApplyResult:
    """Refuses (never records an exit) unless `can_exit` is real-true
    right now. This is the only way `state.json`'s `active` flag is
    ever cleared - there is no other code path that exits recovery
    mode, so the hard exit condition holds by construction, not by
    every caller remembering to check it first."""
    ok, reason = can_exit(runner, personas=personas, mount_table_path=mount_table_path)
    if not ok:
        return ApplyResult(False, reason)
    state = read_state(runner, state_path=state_path) or {"reason": "unknown", "entered_at": now}
    state["active"] = False
    state["exited_at"] = now
    _write_state(runner, state)
    return ApplyResult(True, reason)
