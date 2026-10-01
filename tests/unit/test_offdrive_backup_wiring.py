"""How the add-only off-drive backup is wired in: settings, sources, the entry point,
the systemd unit and timer, and provisioning (v0.2 row 56)."""
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import offdrive_backup as ob
import settings_store


@pytest.fixture(autouse=True)
def _asked_by_the_web_app(monkeypatch):
    """These tests exercise the backup itself; each call carries a genuinely signed web origin."""
    import web_origin_helper as woh
    gate = woh.configured_gate()
    for name in ("run_backup", "main"):
        real = getattr(ob, name)

        def wrapper(*a, _real=real, **kw):
            kw.setdefault("origin", woh.origin_for("backup_offdrive", {"dry_run": kw.get("dry_run", False),
                                                                        "force": kw.get("force", False)}, gate=gate))
            return _real(*a, **kw)
        monkeypatch.setattr(ob, name, wrapper)


ROOT = Path(__file__).resolve().parents[2]
PROVISION = (ROOT / "boot" / "provision.sh").read_text()


# --- settings ---------------------------------------------------------------

def test_the_destination_setting_defaults_to_nothing_so_no_drive_is_written_by_default():
    assert settings_store.get_setting("backups", "offdrive_destination") == ""


def test_the_minimum_interval_defaults_to_a_week():
    assert settings_store.get_setting("backups", "offdrive_min_interval_hours") == 168


# --- which sources are backed up --------------------------------------------

def test_sources_cover_the_baseline_volumes_but_not_the_ephemeral_one(monkeypatch):
    srcs = ob.build_sources(is_mount=lambda p: True, exists=lambda p: True)
    vols = srcs["baseline-volumes"]
    assert "/mnt/SESSION_TEMP" not in vols            # non-persistent by design
    for needed in ("/mnt/BASELINE", "/mnt/SUBSTRATE", "/mnt/USER_ADMIN", "/mnt/USER_PERSONAL"):
        assert needed in vols


def test_the_installer_cache_has_its_own_changes_only_archive():
    srcs = ob.build_sources(is_mount=lambda p: True, exists=lambda p: True)
    assert srcs["installer-cache"] == ["/mnt/INSTALLER_CACHE"]
    assert "/mnt/INSTALLER_CACHE" not in srcs["baseline-volumes"]
    assert "installer-cache" in ob.CHANGES_ONLY_LABELS and "baseline-volumes" not in ob.CHANGES_ONLY_LABELS


def test_main_asks_for_the_cache_to_be_changes_only(monkeypatch):
    seen = {}
    monkeypatch.setattr(ob, "run_backup", lambda **kw: seen.update(kw) or ob.BackupResult(None, False, True, 0, "skipped"))
    monkeypatch.setattr(ob, "build_sources", lambda **k: {"installer-cache": ["/mnt/INSTALLER_CACHE"]})
    monkeypatch.setattr(ob, "_boot_serial", lambda: None)
    ob.main(get_setting=lambda g, k: S[(g, k)], now=lambda: 1.0, print_fn=lambda l: None)
    assert seen["changes_only"] == frozenset({"installer-cache"})


def test_a_volume_that_is_not_mounted_is_skipped_not_backed_up_as_an_empty_directory():
    srcs = ob.build_sources(is_mount=lambda p: p != "/mnt/USER_PERSONAL", exists=lambda p: True)
    assert "/mnt/USER_PERSONAL" not in srcs["baseline-volumes"]
    assert "/mnt/USER_ADMIN" in srcs["baseline-volumes"]


def test_proxmox_config_is_included_when_it_exists():
    srcs = ob.build_sources(is_mount=lambda p: True, exists=lambda p: p in ("/etc/pve", "/etc/hostname"))
    assert srcs["proxmox-config"] == ["/etc/pve", "/etc/hostname"]


def test_labels_with_nothing_to_back_up_are_left_out():
    srcs = ob.build_sources(is_mount=lambda p: False, exists=lambda p: False)
    assert srcs == {}


# --- the entry point --------------------------------------------------------

def _main(monkeypatch, *, settings, result=None, boom=None):
    seen = {}

    def fake_run_backup(**kw):
        seen.update(kw)
        if boom:
            raise boom
        return result or ob.BackupResult(Path("/x/baseline-1"), True, False, 123, "ok")

    monkeypatch.setattr(ob, "run_backup", fake_run_backup)
    monkeypatch.setattr(ob, "build_sources", lambda **k: {"baseline-volumes": ["/mnt/BASELINE"]})
    monkeypatch.setattr(ob, "_boot_serial", lambda: "BOOT-SERIAL")
    lines = []
    rc = ob.main(get_setting=lambda g, k: settings[(g, k)], now=lambda: 1_800_000_000.0, print_fn=lines.append)
    return rc, seen, lines


S = {("backups", "offdrive_destination"): "/mnt/10TB/backup", ("backups", "offdrive_min_interval_hours"): 168}


def test_main_passes_the_configured_destination_and_the_two_allowed_drives(monkeypatch):
    rc, seen, _ = _main(monkeypatch, settings=S)
    assert rc == 0 and seen["destination"] == "/mnt/10TB/backup"
    assert seen["allowed_serials"] == frozenset({"MD89N41071210AP4E", "FD01N6557110C271B"})
    assert seen["boot_serial"] == "BOOT-SERIAL" and seen["min_interval_hours"] == 168
    assert callable(seen["record_success"])


def test_main_fails_visibly_when_no_destination_is_configured(monkeypatch):
    rc, _, lines = _main(monkeypatch, settings={**S, ("backups", "offdrive_destination"): ""})
    assert rc == 1 and any("destination" in l.lower() for l in lines)


def test_main_reports_a_refusal_and_exits_non_zero(monkeypatch):
    rc, _, lines = _main(monkeypatch, settings=S, boom=ob.BackupError("destination is on one of the SK hynix drives"))
    assert rc == 1 and any("SK hynix" in l for l in lines)


def test_main_treats_a_skip_as_success(monkeypatch):
    skipped = ob.BackupResult(None, False, True, 0, "skipped: a backup newer than 168h already exists")
    rc, _, lines = _main(monkeypatch, settings=S, result=skipped)
    assert rc == 0 and any("skipped" in l for l in lines)


def test_main_never_forces_a_backup(monkeypatch):
    _, seen, _ = _main(monkeypatch, settings=S)
    assert not seen.get("force")


# --- no script or timer entry point: only the web application can start a backup ----------

@pytest.mark.parametrize("gone", [
    "baseline/bin/baseline-backup-offdrive", "boot/baseline-backup-offdrive.service",
    "boot/baseline-backup-offdrive.timer", "baseline/bin/baseline-backup-recurring",
    "boot/baseline-backup-recurring.service", "boot/baseline-backup-recurring.timer",
])
def test_there_is_no_script_service_or_timer_that_starts_a_backup(gone):
    assert not (ROOT / gone).exists()


def test_provisioning_installs_the_web_side_and_no_backup_timer():
    for needle in ("baseline/lib/offdrive_backup.py", "baseline/lib/web_gate.py", "baseline/lib/operations.py"):
        assert needle in PROVISION
    assert "backup-offdrive" not in PROVISION and "backup-recurring" not in PROVISION


def test_main_passes_a_dry_run_flag_through(monkeypatch):
    seen = {}
    monkeypatch.setattr(ob, "run_backup", lambda **kw: seen.update(kw) or ob.BackupResult(None, False, False, 5, "dry run: nothing was written"))
    monkeypatch.setattr(ob, "build_sources", lambda **k: {"baseline-volumes": ["/mnt/BASELINE"]})
    monkeypatch.setattr(ob, "_boot_serial", lambda: None)
    rc = ob.main(get_setting=lambda g, k: S[(g, k)], now=lambda: 1.0, print_fn=lambda l: None, dry_run=True)
    assert rc == 0 and seen["dry_run"] is True
