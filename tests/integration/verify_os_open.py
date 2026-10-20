#!/usr/bin/env python3
"""Open one OS carried on this drive's INSTALLER_CACHE/isos, through the same code the web app's VM page uses.

Run on an installed Baseline Proxmox host (the allscript rehearsal does, in its VM). Creates a VM from the named image
(vm_page.perform create_iso), starts it, waits, and reports whether it is still running and whether its screen shows
anything. Prints one JSON line and writes /var/log/baseline-os-open.json. Not run by the unit tests: it needs a real
Proxmox host and KVM.
"""
import json
import socket
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "baseline/lib"))
import baseline_web
import vm_host as vh
import vm_page

ISOS = Path("/mnt/INSTALLER_CACHE/isos")
NAME = "os-open-check"


def nonblack_fraction(ppm: bytes) -> float:
    header, rest = ppm.split(b"\n255\n", 1)
    return sum(1 for b in rest[::97] if b > 16) / max(1, len(rest[::97]))


def screendump(vmid, path: Path) -> None:
    """Ask the VM's own QMP socket (Proxmox keeps one per VM) for a PPM of its screen."""
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(30)
        sock.connect(f"/var/run/qemu-server/{vmid}.qmp")
        stream = sock.makefile("rw")
        stream.readline()                                    # greeting
        for command in ({"execute": "qmp_capabilities"},
                        {"execute": "screendump", "arguments": {"filename": str(path)}}):
            stream.write(json.dumps(command) + "\n")
            stream.flush()
            reply = json.loads(stream.readline())
            if "error" in reply:
                raise ValueError(f"{command['execute']}: {reply['error'].get('desc', reply['error'])}")


def main(image: str, max_seconds: int = 600) -> int:
    host = baseline_web._vm_host_for({})
    report = {"image": image, "backend": getattr(host, "backend", "QEMU")}
    listed = {Path(i["path"]).name: i["name"] for i in vm_page.available_isos(host, ISOS)}
    image = listed.get(image, image)           # the VM page names an image by its Proxmox storage volume
    steps = (("create_iso", {"name": NAME, "iso": image, "disk_gb": 8, "memory_mb": 2048, "cpus": 2}),
             ("start", {"name": NAME, "display": "vnc"}))
    for action, params in steps:
        result = vm_page.perform(host, action, params, iso_dir=ISOS)
        report[action] = result
        if not result.get("ok"):
            break
    else:
        deadline = time.monotonic() + max_seconds
        record = host._record(NAME) if hasattr(host, "_record") else None
        shot = Path(tempfile.mkdtemp()) / "screen.ppm"
        while True:
            time.sleep(15)
            report["running"] = bool(host.status(NAME).get("running"))
            if record and record.get("vmid"):
                try:
                    screendump(record["vmid"], shot)
                    report["screen_nonblack_fraction"] = round(nonblack_fraction(shot.read_bytes()), 3)
                except (OSError, ValueError) as exc:
                    report["screendump"] = str(exc)
            if (report["running"] and report.get("screen_nonblack_fraction", 0) > 0.02) or time.monotonic() > deadline:
                break
        report["seconds_to_open"] = round(max_seconds - (deadline - time.monotonic()))
    report["opened"] = bool(report.get("running")) and report.get("screen_nonblack_fraction", 0) > 0.02
    Path("/var/log/baseline-os-open.json").write_text(json.dumps(report, indent=1))
    print("OS-OPEN " + json.dumps(report))
    return 0 if report["opened"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
