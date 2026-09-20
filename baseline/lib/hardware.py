#!/usr/bin/env python3
"""Baseline Hardware Contract - Step 4.

Collector: shells out to inxi, produces raw evidence.
Normalizer: strips inxi's internal ordering-prefixed keys ("003#1#0#CPU")
and folds the result into the Baseline Hardware Schema. Consumers (CLI,
harness tools, snapshot/diff) depend only on the normalized schema below,
never on inxi's own output shape - inxi is one collector among several
this contract can grow (lspci/lsusb/udevadm/lsblk/ip/ethtool/lshw).
"""
import json
import re
import subprocess
import sys
import tempfile
import os
from pathlib import Path

SCHEMA_VERSION = 1
KEY_RE = re.compile(r"^\d+#\d+#\d+#(.*)$")


def _clean_key(k: str) -> str:
    m = KEY_RE.match(k)
    return m.group(1) if m else k


def _clean(obj):
    if isinstance(obj, dict):
        return {_clean_key(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def _section(raw, name):
    """Find a top-level inxi section by cleaned name, merge its sub-entries."""
    for entry in raw:
        for k, v in entry.items():
            if _clean_key(k) == name:
                merged = {}
                for part in v:
                    if isinstance(part, dict):
                        merged.update(part)
                return merged
    return {}


def _explicit_tty_stdin():
    """A real, explicitly-opened fd for our own controlling tty, or None.

    inxi refuses most options ("You can't run option ... in an IRC
    client!") whenever its stdin doesn't look like a terminal - it
    decides this by shelling out to `tty` itself. Under Baseline's
    Textual app, inxi is launched from a worker *thread*, and simply
    inheriting fd 0 from the process doesn't reliably read back as a
    tty to that check even though the process's own stdin genuinely is
    one (confirmed live: inxi succeeds when handed an explicitly-opened
    fd for the same tty, and fails with the exact IRC-client message
    when it inherits fd 0 as-is). Opening our own controlling tty by
    name and handing inxi that fd directly sidesteps the discrepancy.
    """
    try:
        if not os.isatty(0):
            return None
        return os.open(os.ttyname(0), os.O_RDWR)
    except OSError:
        return None


def collect(timeout: int = 15):
    """Run inxi, return (cleaned_raw, error|None)."""
    fd, path = tempfile.mkstemp(prefix="baseline_hw_", suffix=".json")
    os.close(fd)
    tty_fd = _explicit_tty_stdin()
    try:
        proc = subprocess.run(
            ["inxi", "-Fmrsiaxxxz", "--output", "json", "--output-file", path],
            capture_output=True, text=True, timeout=timeout,
            stdin=tty_fd if tty_fd is not None else subprocess.DEVNULL,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip() or f"inxi exited {proc.returncode}"
            return None, detail
        with open(path) as f:
            text = f.read()
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return None, str(e)
    finally:
        if tty_fd is not None:
            try:
                os.close(tty_fd)
            except OSError:
                pass
        try:
            os.unlink(path)
        except OSError:
            pass
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"bad inxi JSON: {e}"
    return _clean(raw), None


def normalize(raw):
    """Fold cleaned inxi output into the Baseline Hardware Schema."""
    system = _section(raw, "System")
    machine = _section(raw, "Machine")
    memory = _section(raw, "Memory")
    cpu = _section(raw, "CPU")
    graphics = _section(raw, "Graphics")
    network = _section(raw, "Network")
    drives = _section(raw, "Drives")

    return {
        "schema_version": SCHEMA_VERSION,
        "system": {
            "kernel": system.get("Kernel"),
            "distro": system.get("Distro"),
            "arch": system.get("arch"),
        },
        "machine": {
            "type": machine.get("Type"),
            "system": machine.get("System"),
            "product": machine.get("product"),
        },
        "cpu": {
            "model": cpu.get("model"),
            "cores": cpu.get("cpus"),
        },
        "memory": {
            "total": memory.get("total"),
            "used": memory.get("used"),
            "available": memory.get("available"),
        },
        "graphics": graphics,
        "network": network,
        "drives": drives,
    }


# Fields likely to be a human-meaningful name for an inxi "item" (one
# dict inside a section's list) - checked in order, first match wins.
_NAME_KEYS = ("Device", "IF", "ID", "IF-ID", "Monitor", "System", "Type", "Kernel", "Info")


def _item_label(item: dict, index: int) -> str:
    for key in _NAME_KEYS:
        val = item.get(key)
        if val:
            return str(val)
    for v in item.values():
        if isinstance(v, str) and v.strip():
            return v
    return f"Item {index + 1}"


def _item_fields(item: dict) -> dict:
    """Scalar fields only - inxi nests some sub-lists (e.g. Repos) that
    don't belong in a flat detail view."""
    return {k: v for k, v in item.items() if not isinstance(v, (dict, list))}


def _item_detail(fields: dict) -> str:
    parts = [f"{k}: {v}" for k, v in fields.items() if v not in (None, "", {})]
    return ", ".join(parts)


def full_inventory(raw):
    """Every hardware fact inxi reported, grouped by inxi's own top-level
    sections - not folded into the fixed Baseline Hardware Schema shape.
    Each inxi "item" (one dict inside a section's list) becomes one row:
    its own identifying field as the label, every other scalar field
    flattened into a detail string and kept as a dict for a detail view.
    inxi interleaves a device's static info and live state as separate,
    adjacent items rather than one merged record per device - this stays
    faithful to that rather than guessing at how to re-pair them."""
    rows = []
    for entry in raw:
        for key, items in entry.items():
            group = _clean_key(key)
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                fields = _item_fields(item)
                if not fields:
                    continue
                label = _item_label(item, i)
                rows.append({
                    "group": group,
                    "label": label,
                    "detail": _item_detail(fields),
                    "fields": fields,
                })
    display = display_mode()
    rows.append({
        "group": "Display",
        "label": display["mode"],
        "detail": _item_detail(display),
        "fields": display,
    })
    return rows


def display_mode() -> dict:
    """Which of the three real console display modes is active, and at
    what resolution/character grid - not from inxi (it doesn't report
    this), read from sysfs plus the process's own already-open stdout.
    Distinguishes:
    - "KMS" (best case): an accelerated DRM driver owns the framebuffer
      (fb0 name ends "drmfb", e.g. "i915drmfb") - full native panel
      resolution, generous character grid.
    - "boot framebuffer" (degraded): fb0 exists but via efifb/vesafb -
      whatever resolution firmware/GRUB happened to hand off, not
      guaranteed to match the panel's native resolution.
    - "VGA text mode" (worst case): no framebuffer driver at all -
      fixed 80x25, happens with nomodeset/vga=normal or genuinely
      unsupported hardware.
    Reported here so a deployment on different hardware shows which
    path it's actually on as a visible fact, not a silent assumption.

    Deliberately does NOT open /dev/tty1 (or any tty device node) as a
    new file descriptor - an earlier version of this function did, via
    a fresh open() + TIOCGWINSZ ioctl, and was followed by the
    console's font/glyph-mapping table getting corrupted ("garble").
    Never proven as the exact mechanism, but removing that open() and
    switching to os.get_terminal_size() (which queries the process's
    own already-open stdout, fd 1 - the exact same tty, no new fd)
    correlated with the corruption not recurring. Kept that way here as
    the safer choice even though it's unconfirmed causation - see
    docs/changelog/hardware/001.md."""
    fb_name = None
    fb_size = None
    try:
        fb_name = Path("/sys/class/graphics/fb0/name").read_text().strip()
    except OSError:
        pass
    try:
        fb_size = Path("/sys/class/graphics/fb0/virtual_size").read_text().strip()
    except OSError:
        pass

    if fb_name and fb_name.endswith("drmfb"):
        mode = f"KMS ({fb_name})"
    elif fb_name in ("efifb", "vesafb"):
        mode = f"boot framebuffer ({fb_name})"
    elif fb_name:
        mode = f"framebuffer ({fb_name})"
    else:
        mode = "VGA text mode (no framebuffer)"

    try:
        term = os.get_terminal_size()
        grid = f"{term.columns}x{term.lines}"
    except OSError:
        grid = "unknown"

    return {
        "mode": mode,
        "resolution": fb_size.replace(",", "x") if fb_size else "unknown",
        "character_grid": grid,
    }


def main() -> int:
    raw, err = collect()
    if err:
        print(json.dumps({"error": err}), file=sys.stderr)
        return 1
    print(json.dumps(normalize(raw), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
