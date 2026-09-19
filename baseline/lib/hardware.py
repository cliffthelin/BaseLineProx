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


def collect(timeout: int = 15):
    """Run inxi, return (cleaned_raw, error|None)."""
    fd, path = tempfile.mkstemp(prefix="baseline_hw_", suffix=".json")
    os.close(fd)
    try:
        proc = subprocess.run(
            ["inxi", "-Fmrsiaxxxz", "--output", "json", "--output-file", path],
            capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode != 0:
            return None, proc.stderr.strip() or f"inxi exited {proc.returncode}"
        with open(path) as f:
            text = f.read()
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return None, str(e)
    finally:
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


def main() -> int:
    raw, err = collect()
    if err:
        print(json.dumps({"error": err}), file=sys.stderr)
        return 1
    print(json.dumps(normalize(raw), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
