"""Real systemd/iperf3 check; requires root and iperf3 in PATH. No test doubles.

Uses loopback only, ephemeral ports and bounded single-use services. Run explicitly;
this is not a unit-suite fixture or a physical Proxmox deployment test.
"""
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "baseline/lib"))
from config_apply import apply_iperf3_config
from repair import RealRunner


def verify():
    if os.geteuid() != 0:
        raise RuntimeError("Real service/socket ownership verification requires root")
    runner = RealRunner()
    units = []
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    config = {"role": "server", "port": port, "bind_address": "127.0.0.1"}
    try:
        result = apply_iperf3_config(runner, config)
        units.extend(re.findall(r"baseline-iperf3-[a-f0-9]+\.service", result.detail))
        assert result.ok, result.detail
        sockets = subprocess.check_output(["ss", "-H", "-ltnp", f"sport = :{port}"], text=True)
        assert f"127.0.0.1:{port}" in sockets, sockets
        conflict = apply_iperf3_config(runner, config)
        units.extend(re.findall(r"baseline-iperf3-[a-f0-9]+\.service", conflict.detail))
        assert not conflict.ok, conflict.detail
        assert "unit stopped" in conflict.detail, conflict.detail
        # The failed competing request must not stop the original listener.
        client = subprocess.run(["iperf3", "-c", "127.0.0.1", "-p", str(port),
                                 "-t", "1", "-J"], capture_output=True, text=True, timeout=15)
        assert client.returncode == 0, client.stderr or client.stdout
        measurement = json.loads(client.stdout)["end"]["sum_received"]["bits_per_second"]
        assert measurement > 0
        for _ in range(20):
            remaining = subprocess.check_output(["ss", "-H", "-ltnp", f"sport = :{port}"], text=True)
            if not remaining.strip():
                break
            time.sleep(0.1)
        assert not remaining.strip(), "Single-use listener did not exit after transfer"
        installed = apply_iperf3_config(runner, {"role": "client", "peer_address": ""})
        assert installed.ok and "no test was run" in installed.detail
        for invalid in ({"role": "server", "port": 70000},
                        {"role": "invalid"},
                        {"role": "server", "bind_address": "0.0.0.0"}):
            refused = apply_iperf3_config(runner, invalid)
            assert not refused.ok, refused.detail
        original_path = os.environ["PATH"]
        try:
            with tempfile.TemporaryDirectory(prefix="baseline-iperf-missing-") as tool_dir:
                for tool in ("systemd-run", "systemctl", "ss"):
                    executable = shutil.which(tool)
                    if executable is None:
                        raise RuntimeError(f"Required real tool missing: {tool}")
                    Path(tool_dir, tool).symlink_to(executable)
                os.environ["PATH"] = tool_dir
                missing = apply_iperf3_config(runner, {"role": "server", "port": port,
                                                       "bind_address": "127.0.0.1"})
                units.extend(re.findall(r"baseline-iperf3-[a-f0-9]+\.service", missing.detail))
                assert not missing.ok, missing.detail
        finally:
            os.environ["PATH"] = original_path
        print(json.dumps({"ready": result.detail, "conflict": conflict.detail,
                          "loopback_bits_per_second": measurement,
                          "single_use_exit": True, "missing_binary_refused": missing.detail,
                          "installed_without_peer": installed.detail, "invalid_inputs_refused": True,
                          "scope": "actual host systemd and iperf3, loopback; no Proxmox or physical-drive boot proof"}))
    finally:
        for unit in units:
            subprocess.run(["systemctl", "stop", unit], capture_output=True, timeout=10)


if __name__ == "__main__":
    verify()
