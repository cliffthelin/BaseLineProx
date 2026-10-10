"""Real read-back of the target system's CURRENT state, diffed against
a DESIRED exported config - the engine behind the configurator's
"DIFFERENCES" page (direct instruction: auto-detect the drive, then
"check for each of the install points and configurations and able to
highlight the changes").

Scoped honestly to the four subsystems that actually have a real apply
function today (config_apply.py / config_pipeline.py, decision records
50-51): `smartd.conf`, `ethtool`, and the two driver/firmware apt
packages. Nothing here invents a read-back for a setting nothing can
apply yet (GPU driver mode, iperf3, Proxmox Core, VM creation) -
extending this to a fifth subsystem is real, separate follow-up work
each time one gets a real apply function.

The `smartd.conf` round-trip is exact by construction:
`config_apply.build_smartd_conf()` is the only code that ever writes
that file in this project, so parsing its own fixed format back is a
real, deterministic round-trip - not a guess. The `ethtool` read-back
parses the real, standard output shape `ethtool`/`ethtool -k`/
`ethtool -a` produce on any real Linux system (`man ethtool`).

Same `Runner`-injected convention as every other provisioning module.
Runs strictly against the already-installed target's own live state -
never touches or builds an ISO.
"""
from __future__ import annotations

import re

from repair import Runner


class ReadbackError(RuntimeError):
    """REAL-002: current configuration could not be observed reliably."""


SMARTD_CONF_PATH = "/etc/smartd.conf"

_SMARTD_DEFAULTS = {
    "smartd_health_check": False, "smartd_monitor_all": False,
    "smartd_auto_offline": "", "smartd_attribute_autosave": "",
    "smartd_selftest_schedule": "", "smartd_email": "", "smartd_email_frequency": "",
}


def read_current_smartd_config(runner: Runner) -> dict:
    """Exact reverse of config_apply.build_smartd_conf() - an absent
    file (never configured yet) reads back as every default."""
    if not runner.path_exists(SMARTD_CONF_PATH):
        return dict(_SMARTD_DEFAULTS)

    content = runner.read_text(SMARTD_CONF_PATH)
    active = [line.strip() for line in content.splitlines()
              if line.strip() and not line.lstrip().startswith("#")]
    if len(active) != 1 or active[0].split()[0] != "DEVICESCAN":
        raise ReadbackError("REAL-002: smartd config is not a supported single DEVICESCAN record; existing state is unknown")
    tokens = active[0].split()[1:]
    current = dict(_SMARTD_DEFAULTS)
    flags = {"-H":"smartd_health_check", "-a":"smartd_monitor_all"}
    values = {"-o":"smartd_auto_offline", "-S":"smartd_attribute_autosave",
              "-s":"smartd_selftest_schedule", "-m":"smartd_email", "-M":"smartd_email_frequency"}
    seen = set()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in seen:
            raise ReadbackError("REAL-002: duplicate smartd directives require an explicit parser")
        seen.add(token)
        if token in flags:
            current[flags[token]] = True
        elif token in values and i + 1 < len(tokens) and not tokens[i+1].startswith("-"):
            i += 1
            value = tokens[i]
            if token in ("-o", "-S") and value not in ("on", "off"):
                raise ReadbackError("REAL-002: unsupported smartd on/off value")
            current[values[token]] = value
        else:
            raise ReadbackError("REAL-002: unsupported or incomplete smartd directive; existing config must be preserved")
        i += 1
    return current


def read_current_ethtool_config(runner: Runner, interface: str) -> dict:
    """Read actual settings; failed or incomplete reads are errors, never defaults."""
    current = {
        "ethtool_autoneg": "", "ethtool_speed": "", "ethtool_duplex": "", "ethtool_wol": "",
        "ethtool_rx_checksum": False, "ethtool_tx_checksum": False,
        "ethtool_tso": False, "ethtool_gro": False,
        "ethtool_pause_autoneg": False,
    }

    settings_proc = runner.run(["ethtool", interface], timeout=10)
    if settings_proc.returncode != 0:
        raise ReadbackError("REAL-002: ethtool settings query failed; current settings are unknown")
    if not settings_proc.stdout.strip():
        raise ReadbackError("REAL-002: ethtool settings query returned no settings")
    if settings_proc.returncode == 0:
        text = settings_proc.stdout
        m = re.search(r"^\s*Speed:\s*(\d+)Mb/s", text, re.M)
        if m: current["ethtool_speed"] = m.group(1)
        m = re.search(r"^\s*Duplex:\s*(\w+)", text, re.M)
        if m: current["ethtool_duplex"] = m.group(1).lower()
        m = re.search(r"^\s*Auto-negotiation:\s*(\w+)", text, re.M)
        if m: current["ethtool_autoneg"] = m.group(1).lower()
        m = re.search(r"^\s*Wake-on:\s*(\S+)", text, re.M)
        if m: current["ethtool_wol"] = m.group(1)

    features_proc = runner.run(["ethtool", "-k", interface], timeout=10)
    if features_proc.returncode != 0:
        raise ReadbackError("REAL-002: ethtool features query failed; current settings are unknown")
    if not features_proc.stdout.strip():
        raise ReadbackError("REAL-002: ethtool features query returned no settings")
    if features_proc.returncode == 0:
        text = features_proc.stdout
        def feature_on(name):
            m = re.search(rf"^{re.escape(name)}:\s*(\w+)", text, re.M)
            if not m or m.group(1) not in ("on", "off"):
                raise ReadbackError(f"REAL-002: ethtool did not report {name}; value is unknown")
            return m.group(1) == "on"
        current["ethtool_rx_checksum"] = feature_on("rx-checksumming")
        current["ethtool_tx_checksum"] = feature_on("tx-checksumming")
        current["ethtool_tso"] = feature_on("tcp-segmentation-offload")
        current["ethtool_gro"] = feature_on("generic-receive-offload")

    pause_proc = runner.run(["ethtool", "-a", interface], timeout=10)
    if pause_proc.returncode != 0:
        raise ReadbackError("REAL-002: ethtool pause query failed; current settings are unknown")
    if not pause_proc.stdout.strip():
        raise ReadbackError("REAL-002: ethtool pause query returned no settings")
    if pause_proc.returncode == 0:
        m = re.search(r"^Autonegotiate:\s*(\w+)", pause_proc.stdout, re.M)
        if not m or m.group(1) not in ("on", "off"):
            raise ReadbackError("REAL-002: ethtool did not report pause autonegotiation")
        current["ethtool_pause_autoneg"] = m.group(1) == "on"

    if any(current[key] == "" for key in ("ethtool_autoneg", "ethtool_speed", "ethtool_duplex", "ethtool_wol")):
        raise ReadbackError("REAL-002: ethtool settings are incomplete or unsupported")
    return current


def read_current_package_installed(runner: Runner, package: str) -> bool:
    proc = runner.run(["dpkg-query", "-W", "-f=${Status}", package], timeout=10)
    if proc.returncode not in (0, 1):
        raise ReadbackError("REAL-002: package database query failed; installation is unknown")
    if proc.returncode == 1:
        # dpkg-query distinguishes a missing package from a failed database/tool.
        if "no packages found matching" in proc.stderr or "package not found" in proc.stderr:
            return False
        raise ReadbackError("REAL-002: package query failed without a confirmed package absence")
    if not proc.stdout.strip():
        raise ReadbackError("REAL-002: package query returned no status")
    return "install ok installed" in proc.stdout


def diff_config(current: dict, desired: dict) -> list:
    """Pure. One row per key in `desired` (a key `current` doesn't have
    at all reads as `None` and is always reported changed) - keys only
    `current` has are irrelevant to what's being asked for and are not
    reported."""
    rows = []
    for key, desired_value in desired.items():
        current_value = current.get(key)
        rows.append({
            "key": key, "current": current_value, "desired": desired_value,
            "changed": current_value != desired_value,
        })
    return rows


def compute_full_diff(runner: Runner, config: dict, *, network_interface: str) -> list:
    """The real report behind the configurator's DIFFERENCES page: one
    section per real subsystem, each with its own current-vs-desired
    rows. A subsystem the desired config doesn't mention at all is
    still included with an empty change list, so the report always
    names all four real subsystems, not just the ones that happen to
    differ."""
    proxmox = config.get("proxmox") or {}
    drivers = config.get("drivers") or {}
    interface = proxmox.get("ethtool_interface") or network_interface

    sections = []

    smartd_desired = {k: v for k, v in proxmox.items() if k.startswith("smartd_")}
    sections.append({
        "subsystem": "smartd",
        "changes": diff_config(read_current_smartd_config(runner), smartd_desired) if smartd_desired else [],
    })

    ethtool_desired = {k: v for k, v in proxmox.items() if k.startswith("ethtool_") and k != "ethtool_interface"}
    sections.append({
        "subsystem": "ethtool",
        "changes": diff_config(read_current_ethtool_config(runner, interface), ethtool_desired) if ethtool_desired else [],
    })

    cpu_changes = []
    if drivers.get("cpu_microcode"):
        package = drivers.get("cpu_microcode_package") or "amd64-microcode"
        cpu_changes = diff_config(
            {"installed": read_current_package_installed(runner, package)}, {"installed": True})
    sections.append({"subsystem": "cpu_microcode", "changes": cpu_changes})

    wifi_changes = []
    if drivers.get("nic_wifi_firmware"):
        package = drivers.get("wifi_firmware_package") or "firmware-mediatek"
        wifi_changes = diff_config(
            {"installed": read_current_package_installed(runner, package)}, {"installed": True})
    sections.append({"subsystem": "wifi_firmware", "changes": wifi_changes})

    return sections
