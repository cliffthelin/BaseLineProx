"""Diagnostic tool collectors - capability detection and normalized
output (PRD SS5.9a).

Extends the existing `hardware.py`/`network.py` collector family
rather than growing either past its current scope. Every collector
here:

- Goes through the same `Runner`-injectable subprocess boundary
  `repair.py` already established, so every collector is
  unit-testable with no real hardware, no real binary, no root.
- Returns a structured result with an explicit `available: bool` and,
  when false, a `reason` - never raises, never blocks the caller. A
  missing tool or absent sensor/drive/interface is a normal, expected
  outcome (confirmed directly against a real automated-install QEMU
  target in decision record 22: sensors/nvme/smartctl all correctly
  reported "no hardware" on that virtio-only VM), not an error.
- Separates capability *detection* (is the tool present, is
  compatible hardware present) from capability *use* (running the
  actual query) as a cheap first step, matching PRD SS5.9's
  functional milestones (nvme list before smart-log; smartctl
  --scan-open before -a; ethtool never assumes an interface name).

`iperf3` is deliberately not a passive collector here - PRD SS5.9a
requires it stay outside the passive context blob as a distinct,
explicitly operator-confirmed action with both endpoints chosen by
the operator. See `iperf3_client_server_test` at the bottom, which is
never called by anything in this module or by any first-boot/harness
path automatically.

Governing constraint, unchanged from the PRD's SS2 architectural
principle: the AI harness receives zero tool-calling capability and
only ever sees a context blob Baseline's own deterministic code
assembled - nothing here creates a path, direct or indirect, for the
harness to invoke any of these five tools itself.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:
        def run(self, argv, timeout=10):
            raise NotImplementedError


def _parse_json(text: str):
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 1. lm-sensors
# ---------------------------------------------------------------------------

@dataclass
class SensorsResult:
    available: bool
    reason: str = ""
    chips: list = field(default_factory=list)


def collect_sensors(runner: Runner) -> SensorsResult:
    proc = runner.run(["sensors", "-j"], timeout=10)
    if proc.returncode != 0:
        return SensorsResult(available=False, reason="sensors exited non-zero (no sensors found or not permitted)")
    data = _parse_json(proc.stdout)
    if data is None:
        return SensorsResult(available=False, reason="sensors -j produced no parseable JSON")
    if not data:  # {} - binary ran fine but found nothing
        return SensorsResult(available=False, reason="no sensor chips detected")

    chips = []
    for chip_name, chip_data in data.items():
        if not isinstance(chip_data, dict):
            continue
        features = []
        for feature_label, feature_data in chip_data.items():
            if feature_label == "Adapter" or not isinstance(feature_data, dict):
                continue
            for sub_label, value in feature_data.items():
                features.append({"label": f"{feature_label} {sub_label}", "value": value, "unit": _guess_unit(sub_label)})
        chips.append({"chip": chip_name, "features": features})
    return SensorsResult(available=bool(chips), reason="" if chips else "no usable chip features", chips=chips)


def _guess_unit(sub_label: str) -> str:
    if "temp" in sub_label.lower() or sub_label.endswith("_input") and "fan" not in sub_label.lower():
        return "C"
    if "fan" in sub_label.lower():
        return "RPM"
    if "volt" in sub_label.lower() or sub_label.startswith("in"):
        return "V"
    return ""


# ---------------------------------------------------------------------------
# 2. nvme-cli - two-stage: discover, then query only what was discovered
# ---------------------------------------------------------------------------

@dataclass
class NvmeResult:
    available: bool
    reason: str = ""
    devices: list = field(default_factory=list)


def collect_nvme(runner: Runner) -> NvmeResult:
    proc = runner.run(["nvme", "list", "-o", "json"], timeout=10)
    if proc.returncode != 0:
        return NvmeResult(available=False, reason="nvme list exited non-zero (nvme-cli missing or no permission)")
    data = _parse_json(proc.stdout)
    if data is None:
        return NvmeResult(available=False, reason="nvme list -o json produced no parseable JSON")

    entries = data.get("Devices", []) if isinstance(data, dict) else []
    if not entries:
        return NvmeResult(available=True, reason="", devices=[])  # zero NVMe devices is normal, not an error

    devices = []
    for entry in entries:
        path = entry.get("DevicePath") or entry.get("Device")
        if not path:
            continue
        smart_proc = runner.run(["nvme", "smart-log", path, "-o", "json"], timeout=10)
        health = _parse_json(smart_proc.stdout) if smart_proc.returncode == 0 else None
        devices.append({
            "path": path,
            "model": entry.get("ModelNumber", ""),
            "firmware": entry.get("Firmware", ""),
            "health": health or {},
        })
    return NvmeResult(available=True, devices=devices)


# ---------------------------------------------------------------------------
# 3. smartmontools - discover, then read-only query; self-tests excluded
# ---------------------------------------------------------------------------

@dataclass
class SmartResult:
    available: bool
    reason: str = ""
    devices: list = field(default_factory=list)


def collect_smart(runner: Runner) -> SmartResult:
    proc = runner.run(["smartctl", "--scan-open", "-j"], timeout=15)
    if proc.returncode not in (0, 1, 2, 4):
        # smartctl uses a bitmask exit code; 0 is clean, other low bits can
        # still carry a valid scan result - only treat a hard failure to
        # produce any JSON as "not available".
        pass
    data = _parse_json(proc.stdout)
    if data is None:
        return SmartResult(available=False, reason="smartctl --scan-open produced no parseable JSON")

    entries = data.get("devices", []) if isinstance(data, dict) else []
    if not entries:
        return SmartResult(available=True, reason="", devices=[])  # no scannable devices is normal

    devices = []
    for entry in entries:
        name = entry.get("name")
        if not name:
            continue
        detail_proc = runner.run(["smartctl", "-a", "-j", name], timeout=15)
        detail = _parse_json(detail_proc.stdout) or {}
        devices.append({
            "device": name,
            "type": entry.get("type", ""),
            "model": detail.get("model_name", ""),
            "temperature": detail.get("temperature", {}).get("current"),
            "power_on_hours": detail.get("power_on_time", {}).get("hours"),
            "smart_passed": detail.get("smart_status", {}).get("passed"),
        })
    return SmartResult(available=True, devices=devices)


def initiate_self_test(runner: Runner, device: str, test_type: str) -> dict:
    """Explicit, separate, operator-initiated action - never called by
    collect_smart or any automatic path. `test_type` must be 'short' or
    'long', matching PRD SS5.9a exactly."""
    if test_type not in ("short", "long"):
        return {"started": False, "reason": f"invalid test_type {test_type!r}, must be 'short' or 'long'"}
    proc = runner.run(["smartctl", "-t", test_type, device], timeout=15)
    return {"started": proc.returncode == 0, "reason": "" if proc.returncode == 0 else proc.stderr}


# ---------------------------------------------------------------------------
# 4. ethtool - never assumes an interface name
# ---------------------------------------------------------------------------

@dataclass
class EthtoolResult:
    available: bool
    reason: str = ""
    interfaces: list = field(default_factory=list)


def collect_ethtool(runner: Runner, list_interfaces_fn) -> EthtoolResult:
    """`list_interfaces_fn` is injected (defaults to
    `network.list_interfaces` at the call site) rather than imported
    directly, so this collector never assumes an interface name and
    stays testable without real sysfs access."""
    physical = list_interfaces_fn()
    if not physical:
        return EthtoolResult(available=True, reason="", interfaces=[])  # no physical NICs is a normal case

    interfaces = []
    for nic in physical:
        name = nic["name"] if isinstance(nic, dict) else nic
        proc = runner.run(["ethtool", name], timeout=10)
        if proc.returncode != 0:
            continue
        parsed = _parse_ethtool_text(proc.stdout)
        parsed["name"] = name
        interfaces.append(parsed)
    return EthtoolResult(available=bool(interfaces), reason="" if interfaces else "no interface responded", interfaces=interfaces)


def _parse_ethtool_text(text: str) -> dict:
    result = {"link_detected": None, "speed": None, "duplex": None, "autoneg": None}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Speed:"):
            result["speed"] = line.split(":", 1)[1].strip()
        elif line.startswith("Duplex:"):
            result["duplex"] = line.split(":", 1)[1].strip()
        elif line.startswith("Auto-negotiation:"):
            result["autoneg"] = line.split(":", 1)[1].strip()
        elif line.startswith("Link detected:"):
            result["link_detected"] = line.split(":", 1)[1].strip() == "yes"
    return result


# ---------------------------------------------------------------------------
# 5. iperf3 - NOT a passive collector; explicit operator-confirmed action
# ---------------------------------------------------------------------------

@dataclass
class IperfResult:
    ran: bool
    reason: str = ""
    summary: dict = field(default_factory=dict)


def iperf3_client_server_test(runner: Runner, *, role: str, peer_address: str, port: int = 5201,
                               duration_s: int = 5) -> IperfResult:
    """Never called automatically by anything in this module, any
    first-boot step, or any harness turn - both `role` and
    `peer_address` must be supplied by an operator who explicitly
    confirmed this specific test (PRD SS5.9a). `role='server'` starts
    a one-shot listener (`-1`); `role='client'` connects to
    `peer_address`."""
    if role not in ("client", "server"):
        return IperfResult(ran=False, reason=f"invalid role {role!r}, must be 'client' or 'server'")
    if role == "client" and not peer_address:
        return IperfResult(ran=False, reason="client role requires a peer_address")

    if role == "server":
        argv = ["iperf3", "-s", "-1", "-p", str(port), "-J"]
    else:
        argv = ["iperf3", "-c", peer_address, "-p", str(port), "-t", str(duration_s), "-J"]

    proc = runner.run(argv, timeout=duration_s + 15)
    if proc.returncode != 0:
        return IperfResult(ran=False, reason=proc.stderr or "iperf3 exited non-zero")
    data = _parse_json(proc.stdout) or {}
    return IperfResult(ran=True, summary=data)
