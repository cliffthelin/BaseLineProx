"""Actual kernel firewall, systemd and iperf3 settings tests in a private netns.

Run as root under `unshare --net`. Requires nft/ip/iperf3 in PATH. No
FakeRunner, mock firewall or remote account. This is workflow evidence on
Linux, not physical LAN throughput or native Proxmox boot evidence.
"""
import argparse
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "baseline/lib"))
import lan_firewall
from repair import RealRunner
from settings_web import LocalAppStore, SystemSectionApplier


def verify(phase, standard_port=False):
    if os.stat("/proc/self/ns/net").st_ino == os.stat("/proc/1/ns/net").st_ino:
        raise RuntimeError("Refusing to change the host firewall: run in a private network namespace")
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True)
    subprocess.run(["ip", "address", "add", "10.66.0.1/32", "dev", "lo"], check=True)
    runner = RealRunner()
    rules = lan_firewall.build_ruleset(lan_firewall.DEFAULT_LAN_SUBNETS)
    subprocess.run(["nft", "-f", "-"], input=rules, text=True, check=True)
    listing = subprocess.check_output(["nft", "-j", "list", "table", "inet", lan_firewall.TABLE], text=True)
    print(json.dumps({"actual_firewall_rule_count": sum("rule" in entry for entry in json.loads(listing)["nftables"])}), flush=True)
    active, detail = lan_firewall.verify_active(runner)
    assert active, detail
    if phase == "firewall":
        subprocess.run(["nft", "add", "rule", "inet", lan_firewall.TABLE, "input", "accept"], check=True)
        unsafe, detail = lan_firewall.verify_active(runner)
        assert not unsafe, "Unconditional accept must not qualify as LAN-only"
        subprocess.run(["nft", "-f", "-"], input=lan_firewall.build_ruleset(["192.168.44.0/24", "fd22::/64"]), text=True, check=True)
        custom, detail = lan_firewall.verify_active(runner)
        assert custom, detail
        subprocess.run(["nft", "-f", "-"], input=lan_firewall.build_ruleset(["8.8.8.0/24", "fd22::/64"]), text=True, check=True)
        public, detail = lan_firewall.verify_active(runner)
        assert not public, "Public sources must not qualify as LAN-only"
        subprocess.run(["nft", "delete", "table", "inet", lan_firewall.TABLE], check=True)
        missing, detail = lan_firewall.verify_active(runner)
        assert not missing, "A missing firewall is unavailable, not active"
        print(json.dumps({"active_policy_verified": True, "unsafe_policy_refused": True,
                          "custom_private_policy_verified": True, "public_policy_refused": True,
                          "missing_policy_refused": True,
                          "scope": "actual isolated kernel nftables"}))
        return
    units = set()
    try:
        with tempfile.TemporaryDirectory(prefix="baseline-iperf-settings-") as folder:
            store = LocalAppStore(Path(folder) / "settings.sqlite")
            applier = SystemSectionApplier(store, runner)
            with socket.socket() as reserve:
                reserve.bind(("10.66.0.1", 0))
                port = reserve.getsockname()[1]
            if standard_port:
                port = 5201
            options = {"role": "server"} if standard_port else {"role": "server", "port": port}
            saved = applier.apply("diagnostics", {"iperf3": options})
            assert saved.applied and "no network test" in saved.detail.lower(), saved.detail
            server = applier.run_iperf3(options)
            print(json.dumps({"server_applied": server.applied, "server_detail": server.detail}), flush=True)
            assert server.applied, server.detail
            status = subprocess.check_output(["ss", "-H", "-ltnp", f"sport = :{port}"], text=True)
            pids = re.findall(r"pid=(\d+)", status)
            assert pids, status
            for pid in pids:
                units.update(re.findall(r"baseline-iperf3-[a-f0-9]+\.service", Path(f"/proc/{pid}/cgroup").read_text()))
            client_options = {"role": "client", "peer_address": "10.66.0.1"}
            if not standard_port:
                client_options["port"] = port
            client = applier.run_iperf3(client_options)
            print(json.dumps({"client_applied": client.applied, "client_detail": client.detail}), flush=True)
            assert client.applied and "Mbit/s" in client.detail, client.detail
            assert store.settings()["diagnostics"]["iperf3"].get("port", 5201) == port
            print(json.dumps({"settings_workflow_verified": True, "port": port, "default_port_verified": standard_port,
                              "scope": "real isolated Linux workflow; virtual local transfer, not physical LAN/Proxmox boot"}))
    finally:
        for unit in units:
            subprocess.run(["systemctl", "stop", unit], capture_output=True, timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("firewall", "settings"), default="settings")
    parser.add_argument("--standard-port", action="store_true")
    args = parser.parse_args()
    verify(args.phase, args.standard_port)
