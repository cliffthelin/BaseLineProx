"""Kasm is part of a new setup: provision.sh stages it, a timer builds it once the machine is configured, and a carried base is what it builds from."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path

import kasm_setup as ks

REPO = Path(__file__).resolve().parents[2]
PROVISION = (REPO / "boot/provision.sh").read_text()


def test_provision_stages_the_kasm_files_and_enables_only_the_timer():
    for staged in ("baseline/lib/kasm_setup.py", "baseline/bin/baseline-kasm", "boot/baseline-kasm-setup.service", "boot/baseline-kasm-setup.timer"):
        assert (REPO / staged).is_file() and f'"$SRC/{staged}"' in PROVISION
    assert "systemctl enable baseline-kasm-setup.timer" in PROVISION
    assert "systemctl enable baseline-kasm-setup.service" not in PROVISION        # the timer retries it; the service has no [Install]


def test_the_service_waits_for_a_configured_machine_and_a_running_proxmox():
    unit = (REPO / "boot/baseline-kasm-setup.service").read_text()
    assert "ConditionPathExists=/var/lib/baseline-firstboot/complete" in unit
    for needed in ("pve-cluster.service", "baseline-storage-reconcile.service", "baseline-firstboot.service"):
        assert needed in unit.split("After=")[1].split("\n")[0]
    assert "Nice=10" in unit and "ReadOnlyPaths=/opt/baseline" in unit


def test_the_default_base_is_the_one_carried_in_the_installers_offline_cache():
    from firstboot_statemachine import OFFLINE_REPOSITORY
    assert ks.Layout().base_dir == OFFLINE_REPOSITORY / "kasm"


def _cli():
    loader = importlib.machinery.SourceFileLoader("baseline_kasm_cli", str(REPO / "baseline/bin/baseline-kasm"))
    spec = importlib.util.spec_from_loader("baseline_kasm_cli", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_an_installer_with_no_carried_base_is_skipped_quietly_not_failed(monkeypatch, capsys, tmp_path):
    cli = _cli()
    machine = ks.KasmSetup(ks.Layout(base_dir=tmp_path), run=lambda argv, **k: (0, "[]", ""), vault=object())
    monkeypatch.setattr(cli.kasm_setup, "KasmSetup", lambda **_k: machine)
    assert cli.main(["baseline-kasm", "setup"]) == 0
    assert "no Kasm base" in json.loads(capsys.readouterr().out)["skipped"]


def test_a_stop_is_reported_on_stderr_with_a_failing_exit(monkeypatch, capsys, tmp_path):
    cli = _cli()

    class Stops:
        layout = ks.Layout(base_dir=tmp_path)

        def existing_vmid(self):
            return 100

        def setup(self, passphrase=None):
            raise ks.KasmSetupError("these volumes must be mounted first: /mnt/APPDATA_ADMIN")

    monkeypatch.setattr(cli.kasm_setup, "KasmSetup", lambda **_k: Stops())
    assert cli.main(["baseline-kasm", "setup"]) == 1
    assert "APPDATA_ADMIN" in capsys.readouterr().err


def test_an_unknown_command_is_a_usage_error():
    assert _cli().main(["baseline-kasm", "wipe"]) == 2


# ---- the base travels with the installer's offline cache -----------------------------------------------------------------

import hashlib

import pytest

import offline_cache


def _base(tmp_path, **manifest):
    folder = tmp_path / "base"
    folder.mkdir()
    image = folder / "kasm-base.qcow2"
    image.write_bytes(b"a base image")
    record = {"base": image.name, "sha256": hashlib.sha256(b"a base image").hexdigest(), "kasm_version": "1.19.0", "holds_install_state_or_secrets": False}
    record.update(manifest)
    (folder / "KASM.json").write_text(json.dumps(record))
    return folder


def test_a_checked_base_is_carried_into_the_cache_under_kasm(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    info = offline_cache.carry_kasm_base(_base(tmp_path), cache)
    assert info["kasm_version"] == "1.19.0" and (cache / "kasm/kasm-base.qcow2").read_bytes() == b"a base image" and (cache / "kasm/KASM.json").is_file()
    assert "kasm/kasm-base.qcow2" in offline_cache.build_manifest(cache)                    # so the target's manifest check covers it


def test_a_base_that_does_not_match_its_manifest_is_never_carried(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    with pytest.raises(RuntimeError, match="checksum"):
        offline_cache.carry_kasm_base(_base(tmp_path, sha256="0" * 64), cache)
    assert not (cache / "kasm").exists()


def test_a_base_that_does_not_vouch_for_itself_is_never_carried(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    with pytest.raises(RuntimeError, match="install state"):
        offline_cache.carry_kasm_base(_base(tmp_path, holds_install_state_or_secrets=True), cache)


def test_kasm_setup_waits_for_user_admin_because_its_vault_lives_there():
    assert "/mnt/USER_ADMIN" in ks.Layout().mounts
