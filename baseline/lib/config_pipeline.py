"""The real bridge between the Baseline Install Configurator's exported
JSON and the apply functions already proven in `config_apply.py`.

Direct instruction this module exists to satisfy: "work on wiring all
of this in, so it's utilized during install/setup and automated" - the
configurator's saved values were reviewable/editable but nothing read
them back and applied them. This module is that read-back.

Scope boundary, stated once and enforced by what this module simply
never does: it runs post-install, at firstboot, against the
already-installed system's own live files and packages. It never
reads, writes, or otherwise touches an ISO or any image-build artifact
- that stays entirely `drive_setup_acquire.py`'s domain, untouched by
this module by construction (nothing here takes an ISO path as an
argument, and no code path here can reach one).

Deliberately narrow, matching what actually has a real apply function
today (`config_apply.py`): `smartd.conf` and `ethtool` settings from
the Proxmox Tools tab, and the two driver/firmware apt-get installs
from the Drivers & Hardware tab. Everything else the configurator can
hold - `iperf3`, Proxmox Core, GPU driver mode, VM creation, and every
AI-identified/custom field - has no apply function anywhere yet and is
intentionally left alone here; adding one is real, separate follow-up
work per tool/category, the same discipline decision record 50 already
established, not something this module silently promises.

The config file itself is exported from the configurator artifact (its
own "Export config" action) and placed on the target disk by the
operator before first boot - this module only ever reads it from a
real path on the already-installed filesystem, via the same
`Runner.read_text`/`path_exists` interface every other provisioning
module in this codebase uses.
"""
from __future__ import annotations

import json

import config_apply

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:
        def run(self, argv, timeout=10):
            raise NotImplementedError

        def read_text(self, path):
            raise NotImplementedError

        def path_exists(self, path):
            raise NotImplementedError


DEFAULT_CONFIG_PATH = "/etc/baseline/install-config.json"

_SMARTD_KEYS = (
    "smartd_health_check", "smartd_monitor_all", "smartd_auto_offline",
    "smartd_attribute_autosave", "smartd_selftest_schedule",
    "smartd_email", "smartd_email_frequency",
)
_ETHTOOL_KEYS = (
    "ethtool_autoneg", "ethtool_speed", "ethtool_duplex", "ethtool_wol",
    "ethtool_rx_checksum", "ethtool_tx_checksum", "ethtool_tso",
    "ethtool_gro", "ethtool_pause_autoneg",
)


def load_config(runner: Runner, path: str = DEFAULT_CONFIG_PATH) -> dict | None:
    """None when no config was ever exported - a config file is
    optional; firstboot must proceed without one, applying nothing
    from this pipeline rather than failing."""
    if not runner.path_exists(path):
        return None
    return json.loads(runner.read_text(path))


def _has_any_key(section: dict, keys) -> bool:
    return any(k in section for k in keys)


def apply_stored_config(runner: Runner, config: dict | None, *, network_interface: str) -> dict:
    """Applies every subsystem that has both a real apply function AND
    relevant keys present in the config, independently of the others -
    one subsystem failing (or being absent from the config) never
    skips a different one. Returns {"applied": [...], "skipped": [...],
    "failed": [...]} naming each subsystem, never raising."""
    summary = {"applied": [], "skipped": [], "failed": []}
    if not config:
        summary["skipped"] = ["smartd", "ethtool", "cpu_microcode", "wifi_firmware"]
        return summary

    proxmox = config.get("proxmox") or {}
    drivers = config.get("drivers") or {}
    # The exported config's own ethtool_interface field (the configurator's
    # "Interface to inspect/tune" field) wins when the operator actually
    # set one - `network_interface` is only the fallback for a config that
    # omits it. Found on audit: this field's value used to be read and
    # stored but never actually consulted here, silently discarded.
    resolved_interface = proxmox.get("ethtool_interface") or network_interface

    def run_subsystem(name, present, apply_fn):
        if not present:
            summary["skipped"].append(name)
            return
        result = apply_fn()
        (summary["applied"] if result.ok else summary["failed"]).append(name)

    run_subsystem("smartd", _has_any_key(proxmox, _SMARTD_KEYS),
                  lambda: config_apply.apply_smartd_config(runner, proxmox))
    run_subsystem("ethtool", _has_any_key(proxmox, _ETHTOOL_KEYS),
                  lambda: config_apply.apply_ethtool_config(runner, resolved_interface, proxmox))
    # cpu_microcode_package/wifi_firmware_package default to THIS
    # session's own detected hardware (AMD, MediaTek) only when the
    # exported config omits them - a different target machine (a
    # different CPU vendor, a different Wi-Fi chip) must be able to
    # override the package actually installed, found missing on audit.
    run_subsystem("cpu_microcode", bool(drivers.get("cpu_microcode")),
                  lambda: config_apply.apply_cpu_microcode(
                      runner, package=drivers.get("cpu_microcode_package") or "amd64-microcode"))
    run_subsystem("wifi_firmware", bool(drivers.get("nic_wifi_firmware")),
                  lambda: config_apply.apply_wifi_firmware(
                      runner, package=drivers.get("wifi_firmware_package") or "firmware-mediatek"))

    return summary
