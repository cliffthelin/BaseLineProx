"""The monitor client against a real QEMU: `info status` must return the VM's state every time, and a stopped VM must read as paused.

Not a unit test: it starts qemu-system-x86_64 (machine `none`, no disk, no KVM, nothing on any device). Run:
python3 -m pytest tests/integration/test_qemu_monitor_status.py
"""
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "baseline/lib"))
import drive_setup_install as dsi  # noqa: E402
import install_watch as iw  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("qemu-system-x86_64") is None, reason="needs qemu-system-x86_64")


def test_status_is_read_reliably_from_a_real_monitor_and_a_stopped_vm_is_seen_as_paused(tmp_path):
    sock = tmp_path / "monitor.sock"
    proc = subprocess.Popen(["qemu-system-x86_64", "-machine", "none", "-display", "none", "-S",
                             "-monitor", f"unix:{sock},server,nowait"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            if sock.exists():
                break
            time.sleep(0.1)
        client = dsi._RealInstallProcess.__new__(dsi._RealInstallProcess)
        client._monitor_socket = sock
        states = [iw.parse_status(client.send_monitor_command("info status")) for _ in range(5)]
        assert states == ["paused (prelaunch)"] * 5
        client.send_monitor_command("cont")
        assert iw.parse_status(client.send_monitor_command("info status")) == "running"
        client.send_monitor_command("stop")
        assert iw.parse_status(client.send_monitor_command("info status")) == "paused"
    finally:
        proc.terminate()
        proc.wait(timeout=10)
