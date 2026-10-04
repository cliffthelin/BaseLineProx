"""Selective application of an exported config against an EXISTING
install - the real engine behind the configurator's "Update" modal.
Direct instruction: "the update action... should also allow applying
only code updates and or DRIVERS and or Applications AND or OS
installs AND or only update configs" with configs "selectable as
update or not update in any combination."

Real, honest scope, checked against this codebase rather than assumed:
"code" (updating Baseline's own software), "applications" (the five
diagnostic tools + kiosk, which decision record 53's audit confirmed
are installed unconditionally by real code, never selectively), and
"os" (VM creation, `vm_provision.py`) have NO real apply mechanism
anywhere in this project yet. Selecting one of those three is real -
recorded in the returned summary's `not_available` list - applying it
is not, and this module never pretends otherwise by silently doing
nothing.

"drivers" (the two apt-installed packages) and "configs" (smartd.conf/
ethtool) DO have real apply functions (`config_apply.py`, decision
records 50-51) and are genuinely wired here. "configs" supports true
partial-field selection - `categories["configs"]` may be `True` (every
field), `False`/omitted (none), or a list/set of specific field names.
A whole-file rewrite like `smartd.conf` cannot honor a partial
selection by simply omitting the unselected keys (config_apply.
build_smartd_conf() would then omit their directives entirely,
resetting them) - so an unselected field is instead read back from the
target's own CURRENT real state via `config_diff.py` and merged in
unchanged before the real apply function runs. That merge is what "any
combination" actually requires.
"""
from __future__ import annotations

import config_apply
import config_diff

from repair import Runner


_NOT_YET_WIRED = ("code", "applications", "os")


def _record_not_available(categories: dict, summary: dict) -> None:
    for name in _NOT_YET_WIRED:
        if categories.get(name):
            summary["not_available"].append(name)


def _apply_drivers(runner: Runner, drivers: dict, categories: dict, summary: dict) -> None:
    if not categories.get("drivers"):
        summary["skipped"] += ["cpu_microcode", "wifi_firmware"]
        return

    if drivers.get("cpu_microcode"):
        result = config_apply.apply_cpu_microcode(
            runner, package=drivers.get("cpu_microcode_package") or "amd64-microcode")
        (summary["applied"] if result.ok else summary["failed"]).append("cpu_microcode")
    else:
        summary["skipped"].append("cpu_microcode")

    if drivers.get("nic_wifi_firmware"):
        result = config_apply.apply_wifi_firmware(
            runner, package=drivers.get("wifi_firmware_package") or "firmware-mediatek")
        (summary["applied"] if result.ok else summary["failed"]).append("wifi_firmware")
    else:
        summary["skipped"].append("wifi_firmware")


def _selected_keys(proxmox: dict, selection, prefix: str) -> set:
    all_keys = {k for k in proxmox if k.startswith(prefix)}
    if selection is True:
        return all_keys
    if not selection:
        return set()
    return all_keys & set(selection)


def _apply_configs(runner: Runner, proxmox: dict, selection, network_interface: str, summary: dict) -> None:
    smartd_selected = _selected_keys(proxmox, selection, "smartd_")
    if smartd_selected:
        merged = config_diff.read_current_smartd_config(runner)
        merged.update({k: proxmox[k] for k in smartd_selected})
        result = config_apply.apply_smartd_config(runner, merged)
        (summary["applied"] if result.ok else summary["failed"]).append("smartd")
    else:
        summary["skipped"].append("smartd")

    ethtool_selected = {k for k in _selected_keys(proxmox, selection, "ethtool_") if k != "ethtool_interface"}
    if ethtool_selected:
        interface = proxmox.get("ethtool_interface") or network_interface
        merged = config_diff.read_current_ethtool_config(runner, interface)
        merged.update({k: proxmox[k] for k in ethtool_selected})
        result = config_apply.apply_ethtool_config(runner, interface, merged)
        (summary["applied"] if result.ok else summary["failed"]).append("ethtool")
    else:
        summary["skipped"].append("ethtool")


def apply_selective_update(runner: Runner, config: dict, categories: dict, *,
                            network_interface: str) -> dict:
    """`categories`: a dict with any combination of `code`, `drivers`,
    `applications`, `os` (each `True`/`False`) and `configs`
    (`True`/`False`/omitted, or a list of specific proxmox-tab field
    names to update). Returns {"applied": [...], "skipped": [...],
    "failed": [...], "not_available": [...]} naming each real
    subsystem or requested-but-unwired category - never raises."""
    summary = {"applied": [], "skipped": [], "failed": [], "not_available": []}
    _record_not_available(categories, summary)

    proxmox = config.get("proxmox") or {}
    drivers = config.get("drivers") or {}

    _apply_drivers(runner, drivers, categories, summary)

    configs_selection = categories.get("configs")
    if configs_selection:
        _apply_configs(runner, proxmox, configs_selection, network_interface, summary)
    else:
        summary["skipped"] += ["smartd", "ethtool"]

    return summary
