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


def test_the_destructive_and_mode_commands_need_their_arguments(capsys):
    cli = _cli()
    assert cli.main(["baseline-kasm", "dehydrate"]) == 2 and cli.main(["baseline-kasm", "reset-root"]) == 2
    assert cli.main(["baseline-kasm", "mode"]) == 2 and cli.main(["baseline-kasm", "mode", "snapshot"]) == 2
    assert "needs --yes" in capsys.readouterr().err


def test_mode_and_dehydrate_reach_the_machine_with_the_confirmation(monkeypatch, capsys, tmp_path):
    cli = _cli()
    calls = []

    class Machine:
        layout = ks.Layout(base_dir=tmp_path)

        def set_mode(self, mode):
            calls.append(("mode", mode)); return {"mode": mode}

        def dehydrate(self):
            calls.append(("dehydrate",)); return {"dehydrated": True}

        def reset_root(self, confirm=False):
            calls.append(("reset-root", confirm)); return {"vmid": 100}

    monkeypatch.setattr(cli.kasm_setup, "KasmSetup", lambda **_k: Machine())
    assert cli.main(["baseline-kasm", "mode", "reset"]) == 0
    assert cli.main(["baseline-kasm", "dehydrate", "--yes"]) == 0
    assert cli.main(["baseline-kasm", "reset-root", "--yes"]) == 0
    assert calls == [("mode", "reset"), ("dehydrate",), ("reset-root", True)]


def test_telemetry_commands_reach_the_machine_and_need_a_verb(monkeypatch, capsys, tmp_path):
    cli = _cli()
    assert cli.main(["baseline-kasm", "telemetry"]) == 2 and cli.main(["baseline-kasm", "telemetry", "wipe"]) == 2
    calls = []

    class Machine:
        layout = ks.Layout(base_dir=tmp_path)
        def collect_telemetry(self): calls.append("collect"); return {"collected": True}
        def telemetry_report(self): calls.append("report"); return {"suggestions": []}

    monkeypatch.setattr(cli.kasm_setup, "KasmSetup", lambda **_k: Machine())
    assert cli.main(["baseline-kasm", "telemetry", "collect"]) == 0 and cli.main(["baseline-kasm", "telemetry", "report"]) == 0
    assert calls == ["collect", "report"]


def test_the_telemetry_timer_is_staged_and_enabled_and_waits_for_a_configured_machine():
    for staged in ("boot/baseline-kasm-telemetry.service", "boot/baseline-kasm-telemetry.timer", "baseline/lib/kasm_telemetry.py"):
        assert (REPO / staged).is_file() and f'"$SRC/{staged}"' in PROVISION
    assert "systemctl enable baseline-kasm-telemetry.timer" in PROVISION
    unit = (REPO / "boot/baseline-kasm-telemetry.service").read_text()
    assert "ConditionPathExists=/var/lib/baseline-firstboot/complete" in unit and "telemetry collect" in unit and "ReadOnlyPaths=/opt/baseline" in unit


def test_the_registry_files_travel_with_the_base_into_the_offline_cache(tmp_path):
    base = _base(tmp_path)
    (base / "registry" / "1.1").mkdir(parents=True)
    (base / "registry" / "versions.txt").write_text("1.1\n")
    (base / "registry" / "1.1" / "list.json").write_text("{}")
    cache = tmp_path / "cache"
    cache.mkdir()
    offline_cache.carry_kasm_base(base, cache)
    assert (cache / "kasm/registry/versions.txt").read_text() == "1.1\n" and (cache / "kasm/registry/1.1/list.json").is_file()
    assert "kasm/registry/1.1/list.json" in offline_cache.build_manifest(cache)                    # covered by the cache's manifest like everything else
    bare = tmp_path / "bare"
    bare.mkdir()
    (tmp_path / "x").mkdir()
    other = _base(tmp_path / "x")
    offline_cache.carry_kasm_base(other, bare)
    assert not (bare / "kasm" / "registry").exists()                                                # no registry in the base: none invented
