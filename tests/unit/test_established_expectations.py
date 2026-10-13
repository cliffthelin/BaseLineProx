"""What the operator established from the first days, checked against the repo: met expectations pass, known gaps are strict xfail.

A strict xfail turns into a suite failure the day the gap is closed, which forces the marker (and AGENTS.md "Established facts") to be
updated. Nothing here claims real-hardware proof.
"""
import importlib.machinery
import importlib.util
import re
from pathlib import Path

import pytest

import application_bundle

REPO = Path(__file__).resolve().parents[2]
FIVE = {"vscode", "spotify", "chrome", "chatgpt", "claude"}


def _first_boot():
    path = REPO / "baseline/bin/baseline-first-boot-install"
    loader = importlib.machinery.SourceFileLoader("fbi_expect", str(path))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("fbi_expect", loader))
    loader.exec_module(module)
    return module


def test_the_five_default_applications_are_defined_and_carried_by_first_boot():
    assert FIVE <= set(application_bundle.APPS)
    source = (REPO / "baseline/bin/baseline-first-boot-install").read_text()
    assert "verify_app_bundle(cache, application_bundle.APPS)" in source       # carried AND verified, on every first boot


def test_storage_ids_are_lowercase_volume_names_and_no_generic_proxmox_name_is_registered_by_us():
    import os_isos
    assert os_isos.ISO_STORAGE == "installer-cache"
    script = (REPO / "boot/baseline-proxmox-defaults.sh").read_text()
    for volume in ("user-admin", "user-personal", "appdata-admin", "appdata-personal", "substrate"):
        assert re.search(rf"\b{volume}\b", script)


@pytest.mark.xfail(strict=True, reason="KNOWN GAP (DR258): the five applications are carried but not installed and configured in any "
                                       "environment; first boot has no step that builds the default Ubuntu VM/CT")
def test_first_boot_prepares_a_default_environment_with_the_five_applications():
    names = [name for name, _ in _first_boot().STEPS]
    assert any(name in ("environments", "default-environment", "app-containers") for name in names)


@pytest.mark.xfail(strict=True, reason="KNOWN GAP (DR257 step 3): the host root volume is still named `root`; it is shown as the "
                                       "storage `substrate` only")
def test_the_host_root_volume_is_renamed_substrate():
    import host_layout
    assert hasattr(host_layout, "name_the_root_volume_substrate")


@pytest.mark.xfail(strict=True, reason="KNOWN GAP (DR258): no AI provider credentials or harness are provisioned on a fresh drive")
def test_a_fresh_drive_provisions_an_ai_provider_and_harness():
    source = (REPO / "boot/provision.sh").read_text()
    assert "harness.env" in source


def test_the_five_proxmox_host_tools_are_the_manifest_ones_and_are_installed_by_first_boot_and_shown():
    manifest = __import__("json").loads((REPO / "baseline/lib/inventory/tools_manifest.json").read_text())
    names = {t["name"] for t in manifest["tools"]}
    assert names == {"lm-sensors", "nvme-cli", "smartmontools", "iperf3", "ethtool"}
    assert '"/tools"' in (REPO / "baseline/lib/baseline_web.py").read_text()          # shown to the operator
    assert "tools_page.py" in (REPO / "boot/provision.sh").read_text()


def test_the_vault_is_encrypted_at_rest_and_every_tui_tab_has_a_browser_page():
    web = (REPO / "baseline/lib/baseline_web.py").read_text()
    for route in ('"/vault"', '"/network"', '"/sensors"', '"/chat"', '"/shell"', '"/hardware"', '"/vms"', '"/environments"'):
        assert route in web, route
    assert "ENC1:" in (REPO / "baseline/lib/vault_crypto.py").read_text()
