"""Watchdog logic for an unattended install under QEMU: decide, from what can be observed, whether the install is healthy, quiet, or dead.

The 2026-10-11 rebuild of PC601 sat for over an hour on a paused VM: the drive's USB bridge had dropped off the bus and come back under
another device name, QEMU's I/O to the old node failed (`paused (io-error)`), and nothing was watching the VM's state. A wait loop must
therefore check, every tick, (1) the VM's own state, (2) that the target drive is still at the node QEMU opened, (3) that the screen
is changing, and (4) a time limit for the stage, and it must say so out loud. This module is the pure part: it takes observations and
returns a verdict; the script does the I/O.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

FATAL_STATES = ("paused (io-error)", "internal-error", "guest-panicked", "shutdown", "paused (shutdown)")
USB_DISCONNECT = re.compile(r"^(?P<stamp>\w{3} +\d+ [\d:]{8}) \S+ kernel: usb \S+: USB disconnect")


class WatchError(RuntimeError):
    pass


def parse_status(reply: str) -> str | None:
    """The state from QEMU's `info status` reply ("VM status: running"), or None if the reply carried none."""
    found = re.findall(r"VM status:\s*([^\r\n]+)", reply or "")
    return found[-1].strip() if found else None


def screen_digest(path) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


@dataclass
class Verdict:
    fatal: str | None = None
    alerts: list = field(default_factory=list)


@dataclass
class StageWatch:
    """One wait. `stall_seconds` is how long an unchanging screen is tolerated before it is reported (it may be a legitimate prompt that is
    waiting for a checkpoint); `limit_seconds` is how long the whole stage may take before it is failed."""
    stage: str
    opened_path: str
    started: float
    limit_seconds: float
    stall_seconds: float = 300.0
    last_digest: str | None = None
    last_change: float = 0.0
    last_alert: float = -1e9
    alert_every: float = 120.0

    def __post_init__(self):
        self.last_change = self.started

    def tick(self, now: float, *, status: str | None, device_path: str | None, digest: str | None) -> Verdict:
        v = Verdict()
        if status is None:
            v.alerts.append("the VM's state could not be read from the QEMU monitor")
        elif status in FATAL_STATES or (status.startswith("paused") and status != "paused (prelaunch)"):
            v.fatal = f"the installation VM is not running: {status}"
            return v
        if device_path is None:
            v.fatal = f"the target drive is no longer attached (it was {self.opened_path}); the VM is writing to a device that is gone"
            return v
        if device_path != self.opened_path:
            v.fatal = (f"the target drive moved from {self.opened_path} to {device_path} (its USB bridge reset); "
                       f"the VM still holds the old node and cannot continue")
            return v
        if digest is not None and digest != self.last_digest:
            self.last_digest, self.last_change = digest, now
        quiet = now - self.last_change
        if quiet >= self.stall_seconds and now - self.last_alert >= self.alert_every:
            self.last_alert = now
            v.alerts.append(f"the screen has not changed for {int(quiet // 60)} min; it may be waiting for a checkpoint")
        if now - self.started >= self.limit_seconds:
            v.fatal = f"stage {self.stage} exceeded its {int(self.limit_seconds // 60)} minute limit"
        return v


def usb_disconnects(journal_text: str, *, year: int, now_epoch: float, window_seconds: float) -> int:
    """How many USB disconnects the kernel logged in the last `window_seconds` (from `journalctl -k` text)."""
    import calendar
    import time
    count = 0
    for line in (journal_text or "").splitlines():
        m = USB_DISCONNECT.match(line)
        if not m:
            continue
        try:
            stamp = time.mktime(time.strptime(f"{year} {m['stamp']}", "%Y %b %d %H:%M:%S"))
        except ValueError:
            continue
        if 0 <= now_epoch - stamp <= window_seconds:
            count += 1
    return count
