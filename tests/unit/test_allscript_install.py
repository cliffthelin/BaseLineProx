"""baseline-allscript-install: the script's own decisions (stage order, confirmation, drive refusal, NIC naming).

Everything else it does is sequencing existing, separately tested modules; their behaviour is not re-tested here.
"""
import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "baseline" / "bin" / "baseline-allscript-install"
_loader = importlib.machinery.SourceFileLoader("allscript", str(_PATH))
_spec = importlib.util.spec_from_loader("allscript", _loader)
allscript = importlib.util.module_from_spec(_spec)
_loader.exec_module(allscript)


def test_stages_run_in_the_fixed_order_and_from_resumes_there():
    assert allscript.select_stages(None, None) == list(allscript.STAGES)
    assert allscript.select_stages(None, "cache") == list(allscript.STAGES)[allscript.STAGES.index("cache"):]
    assert allscript.select_stages("kiosk", None) == ["kiosk"]
    # the rehearsal is never part of the real run, and continues through first boot in its own session
    assert "rehearse" not in allscript.select_stages(None, None)
    assert allscript.select_stages("rehearse", None) == ["rehearse", "firstboot", "kiosk"]


def test_unknown_stage_is_refused():
    with pytest.raises(ValueError):
        allscript.select_stages("format-everything", None)
    with pytest.raises(ValueError):
        allscript.select_stages(None, "nope")


def test_wipe_needs_the_exact_typed_phrase_for_that_serial():
    assert allscript.confirmation_ok("WIPE MD89N41071210AP4E", "MD89N41071210AP4E")
    assert allscript.confirmation_ok("  WIPE MD89N41071210AP4E\n", "MD89N41071210AP4E")
    for typed in ("wipe MD89N41071210AP4E", "WIPE", "yes", "", "WIPE FD01N6557110C271B", "WIPE MD89N41071210AP4"):
        assert not allscript.confirmation_ok(typed, "MD89N41071210AP4E")


PC401, PC601 = "MD89N41071210AP4E", "FD01N6557110C271B"


@pytest.fixture
def target(request):
    """Select a target for one test and restore 'no target' afterwards (module globals)."""
    def choose(name):
        allscript.select_target(*allscript.target_for(name, "", ["preflight"]))
    yield choose
    allscript.select_target(None, None, None)


def test_there_is_no_default_target():
    """Two drives, two agents: guessing would be a destructive choice made for someone else."""
    assert allscript.TARGET_NAME is None and allscript.SERIAL is None
    for stages in (["preflight"], ["install"], list(allscript.STAGES)):
        with pytest.raises(ValueError, match="no default"):
            allscript.target_for(None, "", stages)


def test_stages_that_never_touch_a_real_drive_need_no_target():
    assert allscript.target_for(None, "", ["cache"]) == (None, None, None)
    assert allscript.target_for(None, "", allscript.select_stages("rehearse", None)) == (None, None, None)


@pytest.mark.parametrize("name,serial,other", [("PC601", PC601, PC401), ("PC401", PC401, PC601)])
def test_either_drive_can_be_named_and_the_other_is_then_protected(name, serial, other):
    assert allscript.target_for(name, "", ["preflight"]) == (name, serial, other)


def test_an_exact_confirm_wipe_serial_implies_its_drive():
    assert allscript.target_for(None, PC601, ["install"]) == ("PC601", PC601, PC401)


def test_a_target_and_a_confirm_wipe_for_the_other_drive_are_refused():
    with pytest.raises(ValueError, match="refusing"):
        allscript.target_for("PC601", PC401, ["install"])


def test_an_unknown_target_is_refused():
    with pytest.raises(ValueError):
        allscript.target_for("sda", "", ["preflight"])


@pytest.mark.parametrize("name", ["PC601", "PC401"])
def test_the_wipe_flag_must_name_the_chosen_target_exactly(target, name):
    target(name)
    serial = allscript.DRIVES[name]
    other = PC401 if serial == PC601 else PC601
    assert allscript.wipe_authorized(serial)
    for value in ("", other, serial.lower(), serial + " ", "yes"):
        assert not allscript.wipe_authorized(value)


def test_nothing_is_wipe_authorized_without_a_target():
    assert not allscript.wipe_authorized(PC401) and not allscript.wipe_authorized(PC601)


def test_the_protected_drive_can_never_be_the_target(target):
    target("PC601")
    with pytest.raises(RuntimeError):
        allscript.refuse_protected({"path": "/dev/sdb", "serial": "X"}, {"path": "/dev/sdb", "serial": "Y"})
    with pytest.raises(RuntimeError):
        allscript.refuse_protected({"path": "/dev/sdc", "serial": PC401}, None)      # PC401 protected this run
    allscript.refuse_protected({"path": "/dev/sdb", "serial": PC601}, {"path": "/dev/sdc", "serial": PC401})


def test_each_target_has_its_own_work_folder_off_the_repo():
    """Never inside the repo (it may sit on NTFS, where screendumps failed), and never shared between targets."""
    a = allscript.work_dir("PC601", ["preflight"])
    b = allscript.work_dir("PC401", ["preflight"])
    assert a != b
    for folder in (a, b, allscript.work_dir(None, ["rehearse"])):
        assert folder.is_relative_to(allscript.BUILD)
        assert not folder.is_relative_to(_PATH.parents[2])


def test_package_proxy_is_from_the_maintained_source_tree():
    repo = _PATH.parents[2]
    assert allscript.PROXY == repo / "baseline" / "lib" / "installer_package_proxy.py"
    assert allscript.PROXY.is_file()


def test_a_checkpoint_left_by_an_earlier_run_is_cleared_before_waiting(tmp_path):
    stale = tmp_path / "seen-firstboot"
    stale.write_text("")
    allscript.clear_stale_checkpoint(stale)
    assert not stale.exists()
    allscript.clear_stale_checkpoint(stale)          # nothing to clear is not an error


def test_os_images_offered_by_default_are_every_iso_except_the_proxmox_installer_itself():
    available = ["ubuntu.iso", "proxmox-ve-source.iso", "fyde.ova", "notes.txt", "mx.iso"]
    assert allscript.select_os_isos([], available, rehearsal=False) == ["mx.iso", "ubuntu.iso"]
    assert allscript.select_os_isos(["ubuntu.iso"], available, rehearsal=False) == ["ubuntu.iso"]
    with pytest.raises(ValueError):
        allscript.select_os_isos(["missing.iso"], available, rehearsal=False)
    with pytest.raises(ValueError):
        allscript.select_os_isos(["proxmox-ve-source.iso"], available, rehearsal=False)


def test_the_rehearsal_offers_only_the_smallest_image_unless_told_otherwise():
    sizes = {"big.iso": 6, "small.iso": 2, "mid.iso": 3}
    assert allscript.select_os_isos([], list(sizes), rehearsal=True, sizes=sizes) == ["small.iso"]
    assert allscript.select_os_isos(["big.iso"], list(sizes), rehearsal=True, sizes=sizes) == ["big.iso"]


def test_a_cache_without_the_applications_is_not_a_complete_cache(tmp_path):
    assert allscript.cache_status(tmp_path / "none") == "missing"
    (tmp_path / "c").mkdir()
    (tmp_path / "c/MANIFEST.json").write_text("{}")
    assert allscript.cache_status(tmp_path / "c") == "without_apps"
    (tmp_path / "c/apps").mkdir()
    assert allscript.cache_status(tmp_path / "c") == "complete"


def test_a_rebuild_is_seeded_from_every_cache_that_exists(tmp_path):
    root = tmp_path / "INSTALLER_CACHE"
    (root / "packages").mkdir(parents=True)
    (root / "installer/expanded/baseline-cache").mkdir(parents=True)
    older = tmp_path / "offline-cache-before-apps"
    older.mkdir()
    seeds = allscript.cache_seeds(root, [older, tmp_path / "gone"])
    assert seeds == [older, root / "packages", root / "installer/expanded/baseline-cache"]
    assert allscript.cache_seeds(tmp_path / "nothing", []) == []


def test_the_assistant_is_taken_from_cache_first_then_from_the_older_host_location(tmp_path):
    on_cache, on_host = tmp_path / "cache/assistant", tmp_path / "host/assistant"
    on_host.parent.mkdir(parents=True)
    on_host.write_text("x")
    assert allscript.locate_assistant([on_cache, on_host]) == on_host
    on_cache.parent.mkdir(parents=True)
    on_cache.write_text("y")
    assert allscript.locate_assistant([on_cache, on_host]) == on_cache
    assert allscript.locate_assistant([tmp_path / "none"]) == tmp_path / "none"   # reported missing by preflight


def test_only_the_recovery_stage_needs_root_and_install_does_not_once_the_drive_has_no_lvm():
    assert allscript.root_required(["preflight"]) == []
    assert allscript.root_required(["recovery", "cache", "install", "firstboot"]) == ["recovery"]
    assert allscript.root_required(["rehearse"]) == [] and allscript.root_required(["install"]) == []


def test_the_installed_hostname_names_the_drive_it_is_installed_on():
    """The first PC601 install came up as baseline-pc401, a name that belongs to the other effort's drive."""
    assert allscript.fqdn_for("PC601") == "baseline-pc601.local"
    assert allscript.fqdn_for("PC401") == "baseline-pc401.local"
    with pytest.raises(ValueError):
        allscript.fqdn_for("not-a-drive")


def test_refreshing_udevs_view_of_a_device_writes_nothing_and_never_raises(tmp_path):
    """udev re-probes a block device when a writer closes it; the installer's VM leaves its cache blank, which makes the
    data-protection guard misread a drive Baseline itself installed. Opening for write and closing writes no bytes."""
    path = tmp_path / "disk.img"
    path.write_bytes(b"abc" * 1000)
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    assert allscript.refresh_udev_view(path) is True
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert allscript.refresh_udev_view(tmp_path / "missing") is False        # a device it cannot open is only reported


def test_volumes_this_host_has_activated_on_the_target_are_found_without_root():
    listing = {"blockdevices": [{"name": "sdb", "type": "disk", "children": [
        {"name": "sdb1", "type": "part"},
        {"name": "sdb3", "type": "part", "children": [
            {"name": "baseline_1b75-user_admin", "type": "lvm", "mountpoints": [None]},
            {"name": "baseline_1b75-data", "type": "lvm", "children": [{"name": "baseline_1b75-data_tdata", "type": "lvm"}]}]}]}]}
    assert allscript.active_lvm_volumes(listing) == ["baseline_1b75-user_admin", "baseline_1b75-data",
                                                     "baseline_1b75-data_tdata"]
    assert allscript.active_lvm_volumes({"blockdevices": [{"name": "sdb", "type": "disk"}]}) == []


def test_the_identity_stage_is_selectable_alone_and_a_vm_holding_the_device_is_found(tmp_path):
    assert allscript.select_stages("identity", None) == ["identity"]
    proc = tmp_path / "proc"
    for pid, argv in (("101", [b"/usr/bin/qemu-system-x86_64", b"-drive", b"file=/dev/sdb,format=raw,if=none,id=targetdisk"]),
                      ("102", [b"/usr/bin/qemu-system-x86_64", b"-drive", b"file=/dev/sdc,format=raw"]),
                      ("103", [b"/bin/bash", b"/dev/sdz"])):
        (proc / pid).mkdir(parents=True)
        (proc / pid / "cmdline").write_bytes(b"\0".join(argv) + b"\0")
    (proc / "self").mkdir()
    assert allscript.vm_using("/dev/sdc", proc_root=proc) == 102       # found inside "-drive file=/dev/sdc,format=raw"
    assert allscript.vm_using("/dev/sdb", proc_root=proc) == 101
    assert allscript.vm_using("/dev/sdz", proc_root=proc) is None
    assert allscript.vm_using("/dev/sd", proc_root=proc) is None       # a prefix of a device name is not the device


def test_the_self_check_passes_on_this_tree_and_names_a_module_that_lost_its_exports(tmp_path, monkeypatch):
    allscript.self_check()
    monkeypatch.setitem(allscript.REQUIRED_EXPORTS, "identifiers", ("no_such_function",))
    import pytest
    with pytest.raises(RuntimeError, match="no_such_function"):
        allscript.self_check()


def test_the_development_root_password_is_created_once_private_and_never_printed(tmp_path, monkeypatch, capsys):
    import os
    monkeypatch.setattr(allscript, "DEV_PASSWORD_FILE", tmp_path / "pw")
    first = allscript.dev_root_password()
    assert len(first) >= 12 and (tmp_path / "pw").stat().st_mode & 0o777 == 0o600
    assert allscript.dev_root_password() == first                       # stable across rebuilds
    assert first not in capsys.readouterr().out                          # never echoed
    (tmp_path / "pw").write_text("short\n")
    import pytest
    with pytest.raises(RuntimeError):
        allscript.dev_root_password()
    (tmp_path / "pw").write_text("a-long-enough-password\n")
    os.chmod(tmp_path / "pw", 0o644)
    with pytest.raises(RuntimeError):
        allscript.dev_root_password()


def test_the_development_user_travels_as_a_hash_only_and_the_file_must_be_private(tmp_path, monkeypatch, capsys):
    import os
    import pytest
    monkeypatch.setattr(allscript, "DEV_USER_FILE", tmp_path / "dev-user")
    assert allscript.dev_user() is None
    (tmp_path / "dev-user").write_text("baseline:CTEST1!\n")
    os.chmod(tmp_path / "dev-user", 0o644)
    with pytest.raises(RuntimeError):
        allscript.dev_user()
    os.chmod(tmp_path / "dev-user", 0o600)
    value = allscript.dev_user()
    name, hashed = value.split(":", 1)
    assert name == "baseline" and hashed.startswith("$6$") and "CTEST1!" not in value
    assert "CTEST1!" not in capsys.readouterr().out
    (tmp_path / "dev-user").write_text("Bad Name:password\n")
    with pytest.raises(RuntimeError):
        allscript.dev_user()


def test_the_rehearsal_vm_disk_is_smaller_than_the_real_drive_and_leaves_room_for_the_baseline_volumes():
    assert 32 * 2**30 <= allscript.REHEARSAL_DISK_BYTES <= 384 * 2**30 < allscript.SIZE
    used = (allscript.REHEARSAL_LVM["lvm_maxroot"] + allscript.REHEARSAL_LVM["lvm_maxvz"] + allscript.REHEARSAL_LVM["lvm_swapsize"]) * 2**30
    assert allscript.REHEARSAL_DISK_BYTES - used >= 24 * 2**30


def test_a_cache_without_the_kasm_base_is_stale_only_when_one_is_wanted(tmp_path):
    cache = tmp_path / "cache"
    (cache / "apps").mkdir(parents=True)
    (cache / "MANIFEST.json").write_text("{}")
    assert allscript.cache_status(cache, None, kasm_base=None) == "complete"
    assert allscript.cache_status(cache, None, kasm_base=tmp_path / "base") == "stale"
    (cache / "kasm").mkdir()
    (cache / "kasm" / "KASM.json").write_text("{}")
    assert allscript.cache_status(cache, None, kasm_base=tmp_path / "base") == "complete"


def test_the_supported_os_list_chooses_the_images_offered_including_an_ova(monkeypatch):
    available = ["a.iso", "b.iso", "f.ova", "extra.iso", "proxmox-ve-source.iso"]
    listing = [{"iso": "b.iso"}, {"iso": "f.ova"}, {"iso": None}, {"iso": "gone.iso"}]
    listed = allscript.listed_os_images(available, listing)
    assert listed == ["b.iso", "f.ova"]                                                     # the list's order; the one that is not on hand is reported, not offered
    assert allscript.select_os_isos([], available, rehearsal=False, listed=listed) == ["b.iso", "f.ova"]


def test_an_explicit_request_and_the_rehearsal_default_still_win_over_the_list():
    available = ["a.iso", "b.iso"]
    assert allscript.select_os_isos(["a.iso"], available, rehearsal=False, listed=["b.iso"]) == ["a.iso"]
    assert allscript.select_os_isos([], available, rehearsal=True, sizes={"a.iso": 9, "b.iso": 1}, listed=["a.iso"]) == ["b.iso"]
    assert allscript.select_os_isos([], available, rehearsal=False, listed=[]) == ["a.iso", "b.iso"]       # no list: every .iso, as before


def test_a_cache_with_no_ready_made_bases_is_stale_when_bases_are_wanted(tmp_path):
    cache = tmp_path / "c"
    (cache / "apps").mkdir(parents=True)
    (cache / "MANIFEST.json").write_text("{}")
    assert allscript.cache_status(cache, None, os_bases=None) == "complete"
    assert allscript.cache_status(cache, None, os_bases=tmp_path / "bases") == "stale"
    (cache / "os-bases").mkdir()
    (cache / "os-bases" / "debian-base.json").write_text("{}")
    assert allscript.cache_status(cache, None, os_bases=tmp_path / "bases") == "complete"


def test_a_cache_missing_one_of_the_wanted_bases_or_carrying_an_old_copy_of_one_is_stale(tmp_path):
    """Found when the base set grew from two to seven: the cache stage called a two-base cache complete."""
    import json
    cache, bases = tmp_path / "c", tmp_path / "bases"
    (cache / "apps").mkdir(parents=True)
    (cache / "os-bases").mkdir()
    bases.mkdir()
    (cache / "MANIFEST.json").write_text("{}")
    def manifest(folder, os_id, sha):
        (folder / f"{os_id}-base.json").write_text(json.dumps({"base": f"{os_id}-base.qcow2", "sha256": sha, "holds_install_state_or_secrets": False}))
    manifest(bases, "debian", "a" * 64)
    manifest(cache / "os-bases", "debian", "a" * 64)
    assert allscript.cache_status(cache, None, os_bases=bases) == "complete"
    manifest(bases, "ubuntu", "b" * 64)
    assert allscript.cache_status(cache, None, os_bases=bases) == "stale"                    # a wanted base is not carried
    manifest(cache / "os-bases", "ubuntu", "c" * 64)
    assert allscript.cache_status(cache, None, os_bases=bases) == "stale"                    # carried, but an older build of it
    manifest(cache / "os-bases", "ubuntu", "b" * 64)
    assert allscript.cache_status(cache, None, os_bases=bases) == "complete"
