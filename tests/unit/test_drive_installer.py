"""Unit tests for drive_installer.py - the real, unified installer
entry point (corrects a real process failure this session: ad hoc
destructive commands were run directly against real hardware instead
of building this first - see decision record 49).

Single-drive design: BASELINE/USER_PERSISTENCE/INSTALLER_CACHE/
SESSION_TEMP all live on the same physical drive, as additional LVM
logical volumes inside Proxmox's own existing volume group - never a
second drive, never a new partition, and the boot/EFI partitions and
existing root/data logical volumes are never touched by anything in
this module. Idempotent throughout: re-running this against an
already-provisioned drive (e.g. to push an update) must never reformat
an existing, already-created volume - only ever create what's missing.

BASELINE (app/VM/LXC state, decision record 68) was added as a fourth
real volume after this module's docstring had named it from the start
without the code ever actually creating it - a real, previously-latent
gap, not a hypothetical one.

No real lvm/mount is ever invoked - the FakeRunner records every argv
and returns scripted results."""
from fake_runner import FakeProc, FakeRunner

import drive_installer as di


# -- pure argv builders -----------------------------------------------

def test_list_logical_volumes_argv():
    assert di.list_logical_volumes_argv() == ["lvs", "--noheadings", "-o", "vg_name,lv_name"]


def test_vg_free_bytes_argv():
    assert di.vg_free_bytes_argv("pve") == ["vgs", "--noheadings", "--units", "b", "--nosuffix", "-o", "vg_free", "pve"]


def test_create_logical_volume_argv():
    argv = di.create_logical_volume_argv("pve", "baseline_user_persistence", "300G")
    assert argv == ["lvcreate", "-n", "baseline_user_persistence", "-L", "300G", "pve"]


def test_format_and_label_argv_never_used_on_an_existing_volume_by_this_function_alone():
    # The function itself is just the mkfs argv - callers (ensure_volume)
    # are responsible for only calling this on a volume this module
    # just created, never an existing one. See test_ensure_volume_*
    # below for the actual safety guarantee.
    assert di.format_and_label_argv("/dev/pve/baseline_user_persistence", "USER_PERSISTENCE") == [
        "mkfs.ext4", "-F", "-L", "USER_PERSISTENCE", "/dev/pve/baseline_user_persistence",
    ]


def test_mount_argv():
    assert di.mount_argv("/dev/pve/baseline_user_persistence", "/mnt/USER_PERSISTENCE") == [
        "mount", "/dev/pve/baseline_user_persistence", "/mnt/USER_PERSISTENCE",
    ]


def test_makedirs_argv():
    assert di.makedirs_argv("/mnt/USER_PERSISTENCE") == ["mkdir", "-p", "/mnt/USER_PERSISTENCE"]


# -- parsing -------------------------------------------------------------

def test_parse_logical_volumes():
    text = "  pve   root  \n  pve   data  \n  pve   baseline_user_persistence  \n"
    assert di.parse_logical_volumes(text) == [("pve", "root"), ("pve", "data"), ("pve", "baseline_user_persistence")]


def test_parse_logical_volumes_empty():
    assert di.parse_logical_volumes("") == []


def test_lv_exists_true():
    groups = [("pve", "root"), ("pve", "baseline_user_persistence")]
    assert di.lv_exists(groups, vg_name="pve", lv_name="baseline_user_persistence") is True


def test_lv_exists_false():
    groups = [("pve", "root"), ("pve", "data")]
    assert di.lv_exists(groups, vg_name="pve", lv_name="baseline_user_persistence") is False


def test_parse_vg_free_bytes():
    assert di.parse_vg_free_bytes("  107374182400\n") == 107374182400


def test_parse_vg_free_bytes_malformed_returns_none():
    assert di.parse_vg_free_bytes("not a number") is None


# -- ensure_volume(): the core idempotent, never-reformat-existing operation --

def test_ensure_volume_creates_format_and_mounts_when_missing():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["lvs"], FakeProc(0, "  pve   root  \n  pve   data  \n", "")),
    ])
    result = di.ensure_volume(runner, vg_name="pve", lv_name="baseline_user_persistence",
                               size="300G", label="USER_PERSISTENCE", mountpoint="/mnt/USER_PERSISTENCE")
    assert result.ok is True
    assert result.created is True
    kinds = [c[0] for c in runner.calls]
    assert kinds == ["lvs", "lvcreate", "mkfs.ext4", "mkdir", "mount"]


def test_ensure_volume_never_reformats_an_already_existing_volume():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["lvs"], FakeProc(0, "  pve   root  \n  pve   baseline_user_persistence  \n", "")),
    ])
    result = di.ensure_volume(runner, vg_name="pve", lv_name="baseline_user_persistence",
                               size="300G", label="USER_PERSISTENCE", mountpoint="/mnt/USER_PERSISTENCE")
    assert result.ok is True
    assert result.created is False
    kinds = [c[0] for c in runner.calls]
    # lvcreate and mkfs.ext4 must NEVER appear - this is the actual
    # safety guarantee "you should not reformat" requires.
    assert "lvcreate" not in kinds
    assert "mkfs.ext4" not in kinds
    # still ensures the mount exists even for an already-provisioned volume
    assert "mount" in kinds


def test_ensure_volume_reports_the_real_lvcreate_failure_and_never_formats():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["lvs"], FakeProc(0, "  pve   root  \n", "")),
        (lambda a: a[:1] == ["lvcreate"], FakeProc(5, "", "Insufficient free extents")),
    ])
    result = di.ensure_volume(runner, vg_name="pve", lv_name="baseline_user_persistence",
                               size="300G", label="USER_PERSISTENCE", mountpoint="/mnt/USER_PERSISTENCE")
    assert result.ok is False
    assert "Insufficient free extents" in result.detail
    kinds = [c[0] for c in runner.calls]
    assert "mkfs.ext4" not in kinds
    assert "mount" not in kinds


# -- ensure_baseline_volumes(): the top-level idempotent orchestration ----

def test_ensure_baseline_volumes_checks_free_space_before_creating_anything():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["vgs"], FakeProc(0, "1000000000\n", "")),  # ~1GB free - not enough
    ])
    results = di.ensure_baseline_volumes(runner, vg_name="pve")
    assert all(r.ok is False for r in results.values())
    assert "insufficient" in next(iter(results.values())).detail.lower()
    # never even checked lvs / attempted a create when space was insufficient up front
    assert not any(c[0] == "lvcreate" for c in runner.calls)


def test_ensure_baseline_volumes_creates_all_four_when_space_allows():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["vgs"], FakeProc(0, "800000000000\n", "")),  # 800GB free - plenty for all four (650G)
        (lambda a: a[:1] == ["lvs"], FakeProc(0, "  pve   root  \n", "")),
    ])
    results = di.ensure_baseline_volumes(runner, vg_name="pve")
    assert set(results) == {"BASELINE", "USER_PERSISTENCE", "INSTALLER_CACHE", "SESSION_TEMP"}
    assert all(r.ok for r in results.values())


def test_ensure_baseline_volumes_never_touches_boot_or_efi():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["vgs"], FakeProc(0, "500000000000\n", "")),
        (lambda a: a[:1] == ["lvs"], FakeProc(0, "  pve   root  \n", "")),
    ])
    di.ensure_baseline_volumes(runner, vg_name="pve")
    for argv in runner.calls:
        joined = " ".join(argv)
        assert "sdd1" not in joined and "sdd2" not in joined and "efi" not in joined.lower()


# --------------------------------------------------------------------------
# Auto-detecting an existing install - "the ability to auto detect that
# drive" (direct instruction). Reuses the exact same lvs parsing
# ensure_volume() already uses, rather than a second detection mechanism
# that could drift out of sync with it.
# --------------------------------------------------------------------------

def test_detect_existing_baseline_install_true_when_all_four_volumes_present():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["lvs"], FakeProc(
            0,
            "  pve  root\n"
            "  pve  baseline_app_state\n"
            "  pve  baseline_user_persistence\n"
            "  pve  baseline_installer_cache\n"
            "  pve  baseline_session_temp\n",
            "")),
    ])
    result = di.detect_existing_baseline_install(runner, vg_name="pve")
    assert result["has_existing_install"] is True
    assert set(result["found_volumes"]) == {
        "baseline_app_state", "baseline_user_persistence", "baseline_installer_cache", "baseline_session_temp"}
    assert result["missing_volumes"] == []


def test_detect_existing_baseline_install_false_when_none_present():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["lvs"], FakeProc(0, "  pve  root\n", "")),
    ])
    result = di.detect_existing_baseline_install(runner, vg_name="pve")
    assert result["has_existing_install"] is False
    assert result["found_volumes"] == []
    assert set(result["missing_volumes"]) == {
        "baseline_app_state", "baseline_user_persistence", "baseline_installer_cache", "baseline_session_temp"}


def test_detect_existing_baseline_install_false_when_only_some_present():
    """A partial state is reported honestly, never rounded up to
    "existing" or blocked - ensure_baseline_volumes() already creates
    whatever's missing regardless."""
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["lvs"], FakeProc(0, "  pve  root\n  pve  baseline_user_persistence\n", "")),
    ])
    result = di.detect_existing_baseline_install(runner, vg_name="pve")
    assert result["has_existing_install"] is False
    assert result["found_volumes"] == ["baseline_user_persistence"]
    assert set(result["missing_volumes"]) == {"baseline_app_state", "baseline_installer_cache", "baseline_session_temp"}


def test_detect_existing_baseline_install_handles_a_real_lvs_failure():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["lvs"], FakeProc(1, "", "no such volume group")),
    ])
    result = di.detect_existing_baseline_install(runner, vg_name="pve")
    assert result["has_existing_install"] is False
    assert "no such volume group" in result["error"]
