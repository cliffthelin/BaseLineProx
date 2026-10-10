"""Discover a real peer from observed LAN neighbors, using actual short tests.

No account credentials, remote installation or mocked output. Optional discovery
is restricted to directly connected physical private networks of at most /24.
Use the real iperf3 executable path as the first argument.
"""
import argparse
import concurrent.futures
import ipaddress
import json
from pathlib import Path
import ssl
import subprocess
import sys
import urllib.request


def inspect(peer, executable):
    try:
        attempt = subprocess.run([executable, "-c", peer, "-p", "5201", "--connect-timeout", "350",
                                  "-t", "1", "-J"], capture_output=True, text=True, timeout=8)
    except subprocess.TimeoutExpired:
        return {"peer": peer, "error": "real peer probe timed out; availability unknown"}
    result = {"peer": peer, "iperf_exit": attempt.returncode}
    try:
        result["iperf"] = json.loads(attempt.stdout)
    except json.JSONDecodeError:
        result["iperf_error"] = attempt.stderr.strip() or attempt.stdout.strip()
    request = urllib.request.Request(f"https://{peer}:8006/api2/json/version")
    try:
        context = ssl._create_unverified_context()  # discovery only; no credentials sent
        with urllib.request.urlopen(request, context=context, timeout=0.75) as response:
            result["proxmox_version_response"] = json.loads(response.read(16384))
    except Exception as exc:
        result["proxmox_discovery_error"] = str(exc)
    return result


def discover(executable, scan_connected_lan=False, output=None):
    def ip(*args):
        return json.loads(subprocess.check_output(["ip", "-j", *args], text=True))
    interfaces = ip("address")
    local_addresses = {entry["local"] for link in interfaces for entry in link.get("addr_info", [])}
    networks = [ipaddress.ip_network(f'{entry["local"]}/{entry["prefixlen"]}', strict=False)
                for link in interfaces if link["ifname"] != "lo" and link.get("link_type") == "ether"
                for entry in link.get("addr_info", []) if entry.get("family") == "inet"]
    neighbors = ip("neigh")
    peers = set()
    for neighbor in neighbors:
        address = ipaddress.ip_address(neighbor["dst"])
        if (address.version == 4 and address.is_private and not address.is_loopback
                and str(address) not in local_addresses and neighbor.get("lladdr")
                and any(address in network for network in networks)):
            peers.add(str(address))
    if scan_connected_lan:
        physical_networks = {ipaddress.ip_network(f'{entry["local"]}/{entry["prefixlen"]}', strict=False)
                             for link in interfaces if Path("/sys/class/net", link["ifname"], "device").exists()
                             for entry in link.get("addr_info", []) if entry.get("family") == "inet"}
        for network in physical_networks:
            if not network.is_private or network.num_addresses > 256:
                raise RuntimeError(f"Refusing automatic scan beyond a private /24: {network}")
            peers.update(str(address) for address in network.hosts() if str(address) not in local_addresses)
    print(json.dumps({"scope": "connected private LAN" if scan_connected_lan else "observed distinct LAN neighbors",
                      "peer_count": len(peers), "test": "real one-second iperf3 and public Proxmox discovery"}), flush=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=16 if scan_connected_lan else 3) as pool:
        for result in pool.map(lambda peer: inspect(peer, executable), sorted(peers)):
            results.append(result)
            if not scan_connected_lan or result.get("iperf_exit") == 0 or "proxmox_version_response" in result:
                print(json.dumps(result), flush=True)
    if output:
        Path(output).write_text(json.dumps({"scope": "actual short client attempts; no remote modifications",
                                          "results": results}, indent=2) + "\n")
    print(json.dumps({"tested_peers": len(results),
                      "iperf_successes": [r["peer"] for r in results if r.get("iperf_exit") == 0],
                      "proxmox_responses": [r["peer"] for r in results if "proxmox_version_response" in r]}), flush=True)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--scan-connected-lan", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve(strict=True))
    discover(executable, args.scan_connected_lan, args.output)
