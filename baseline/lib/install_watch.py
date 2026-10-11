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
    """The screen reduced to a grid of 16x16-pixel blocks, one character per block ('1' where the block has lit pixels), as a string.
    Compare two with `differs`: a blinking cursor changes one or two blocks, text or progress changes many. (A raw hash changed on every
    tick of an idle prompt and hid a hang.)"""
    try:
        data = Path(path).read_bytes()
        header, rest = data.split(b"\n255\n", 1)
        width, height = (int(x) for x in header.split()[1:3])
    except (OSError, ValueError):
        return None
    block, cells = 16, []
    for by in range(0, height - block + 1, block):
        lit = [0] * (width // block)
        for y in range(by, by + block):
            line = rest[y * width * 3:(y + 1) * width * 3]
            for bx in range(width // block):
                chunk = line[bx * block * 3:(bx + 1) * block * 3]
                lit[bx] += sum(1 for i in range(0, len(chunk), 3) if chunk[i] or chunk[i + 1] or chunk[i + 2])
        cells.extend("1" if n > 6 else "0" for n in lit)
    return "".join(cells)


CURSOR_BLOCKS = 2        # a blinking cursor can change at most this many blocks between two looks


def differs(a: str | None, b: str | None) -> bool:
    """Whether two screen digests are different screens (more than a cursor's worth of blocks changed)."""
    if a is None or b is None or len(a) != len(b):
        return a != b
    return sum(1 for x, y in zip(a, b) if x != y) > CURSOR_BLOCKS


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
        if digest is not None and differs(digest, self.last_digest):
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


def bytes_written(volume) -> int | None:
    """Bytes written to `volume` so far, without root: for a block device the kernel's own counter (/sys/block/<name>/stat, field 7, in
    512-byte sectors, since it appeared); for an image file the space actually allocated. None when it cannot be read."""
    path = Path(volume)
    try:
        if path.is_block_device():
            return int(Path(f"/sys/block/{path.name}/stat").read_text().split()[6]) * 512
        return path.stat().st_blocks * 512
    except (OSError, IndexError, ValueError):
        return None


def throughput_line(previous, current, seconds) -> str:
    """'written 21.0 GiB, 108 MB/s since the last look', or just the total when there is no earlier reading."""
    if current is None:
        return "written: unknown"
    total = f"written {current / 2**30:.1f} GiB"
    if previous is None or seconds <= 0 or current < previous:
        return total
    return f"{total}, {(current - previous) / seconds / 1e6:.0f} MB/s"
