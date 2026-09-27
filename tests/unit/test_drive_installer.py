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


def test_ensure_baseline_volumes_creates_all_five_when_space_allows():
    """Admin + personal, per direct instruction - two USER_PERSISTENCE
    volumes by default, not one (decision record 76)."""
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["vgs"], FakeProc(0, "1100000000000\n", "")),  # 1.1TB free - plenty for all five (950G)
        (lambda a: a[:1] == ["lvs"], FakeProc(0, "  pve   root  \n", "")),
    ])
    results = di.ensure_baseline_volumes(runner, vg_name="pve")
    assert set(results) == {"BASELINE", "USER_PERSISTENCE_ADMIN", "USER_PERSISTENCE_PERSONAL",
                             "INSTALLER_CACHE", "SESSION_TEMP"}
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

def test_detect_existing_baseline_install_true_when_all_volumes_present():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["lvs"], FakeProc(
            0,
            "  pve  root\n"
            "  pve  baseline_app_state\n"
            "  pve  baseline_user_persistence_admin\n"
            "  pve  baseline_user_persistence_personal\n"
            "  pve  baseline_installer_cache\n"
            "  pve  baseline_session_temp\n",
            "")),
    ])
    result = di.detect_existing_baseline_install(runner, vg_name="pve")
    assert result["has_existing_install"] is True
    assert set(result["found_volumes"]) == {
        "baseline_app_state", "baseline_user_persistence_admin", "baseline_user_persistence_personal",
        "baseline_installer_cache", "baseline_session_temp"}
    assert result["missing_volumes"] == []


def test_detect_existing_baseline_install_false_when_none_present():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["lvs"], FakeProc(0, "  pve  root\n", "")),
    ])
    result = di.detect_existing_baseline_install(runner, vg_name="pve")
    assert result["has_existing_install"] is False
    assert result["found_volumes"] == []
    assert set(result["missing_volumes"]) == {
        "baseline_app_state", "baseline_user_persistence_admin", "baseline_user_persistence_personal",
        "baseline_installer_cache", "baseline_session_temp"}


def test_detect_existing_baseline_install_false_when_only_some_present():
    """A partial state is reported honestly, never rounded up to
    "existing" or blocked - ensure_baseline_volumes() already creates
    whatever's missing regardless."""
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["lvs"], FakeProc(0, "  pve  root\n  pve  baseline_user_persistence_admin\n", "")),
    ])
    result = di.detect_existing_baseline_install(runner, vg_name="pve")
    assert result["has_existing_install"] is False
    assert result["found_volumes"] == ["baseline_user_persistence_admin"]
    assert set(result["missing_volumes"]) == {
        "baseline_app_state", "baseline_installer_cache", "baseline_session_temp", "baseline_user_persistence_personal"}


def test_detect_existing_baseline_install_handles_a_real_lvs_failure():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["lvs"], FakeProc(1, "", "no such volume group")),
    ])
    result = di.detect_existing_baseline_install(runner, vg_name="pve")
    assert result["has_existing_install"] is False
    assert "no such volume group" in result["error"]


# --------------------------------------------------------------------------
# Per-mount permission restrictions (real follow-up work, confirmed
# direction: keep the per-role LVM volumes, add per-mount permission
# restriction + per-volume telemetry - decision record 71).
# --------------------------------------------------------------------------

def test_mount_options_restricts_session_temp_and_installer_cache_to_noexec():
    assert "noexec" in di.MOUNT_OPTIONS["SESSION_TEMP"]
    assert "noexec" in di.MOUNT_OPTIONS["INSTALLER_CACHE"]


def test_mount_options_never_restricts_user_persistence_or_baseline_to_noexec():
    # USER_PERSISTENCE_<PERSONA> holds the scripts inbox - an operator
    # may reasonably chmod +x and run a script directly from there.
    assert "noexec" not in di.mount_options_for("USER_PERSISTENCE_ADMIN")
    assert "noexec" not in di.mount_options_for("USER_PERSISTENCE_PERSONAL")
    assert "noexec" not in di.MOUNT_OPTIONS["BASELINE"]


def test_mount_options_applies_nosuid_and_nodev_to_every_volume():
    for label, opts in di.MOUNT_OPTIONS.items():
        assert "nosuid" in opts, label
        assert "nodev" in opts, label


def test_mount_argv_without_options_matches_original_bare_shape():
    assert di.mount_argv("/dev/pve/x", "/mnt/X") == ["mount", "/dev/pve/x", "/mnt/X"]


def test_mount_argv_with_options_includes_dash_o():
    assert di.mount_argv("/dev/pve/x", "/mnt/X", options="defaults,noexec") == [
        "mount", "-o", "defaults,noexec", "/dev/pve/x", "/mnt/X",
    ]


def test_remount_argv_shape():
    assert di.remount_argv("/mnt/X", "defaults,noexec") == [
        "mount", "-o", "remount,defaults,noexec", "/mnt/X",
    ]


def test_fstab_line_shape():
    assert di.fstab_line("/dev/pve/x", "/mnt/X", "defaults,noexec") == \
        "/dev/pve/x /mnt/X ext4 defaults,noexec 0 2\n"


def test_ensure_volume_mounts_a_new_volume_with_its_real_role_options():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["lvs"], FakeProc(0, "  pve   root  \n", "")),
    ])
    di.ensure_volume(runner, vg_name="pve", lv_name="baseline_session_temp",
                      size="50G", label="SESSION_TEMP", mountpoint="/mnt/SESSION_TEMP")
    mount_calls = [c for c in runner.calls if c[0] == "mount"]
    assert len(mount_calls) == 1
    assert mount_calls[0] == ["mount", "-o", di.MOUNT_OPTIONS["SESSION_TEMP"],
                               "/dev/pve/baseline_session_temp", "/mnt/SESSION_TEMP"]


def test_ensure_volume_writes_a_real_fstab_entry_for_a_new_volume():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["lvs"], FakeProc(0, "  pve   root  \n", "")),
    ])
    di.ensure_volume(runner, vg_name="pve", lv_name="baseline_session_temp",
                      size="50G", label="SESSION_TEMP", mountpoint="/mnt/SESSION_TEMP")
    assert di.FSTAB_PATH in runner.appends
    assert di.fstab_line("/dev/pve/baseline_session_temp", "/mnt/SESSION_TEMP",
                          di.MOUNT_OPTIONS["SESSION_TEMP"]) in runner.files[di.FSTAB_PATH]


def test_ensure_volume_never_duplicates_an_existing_fstab_entry():
    existing_line = di.fstab_line("/dev/pve/baseline_session_temp", "/mnt/SESSION_TEMP",
                                   di.MOUNT_OPTIONS["SESSION_TEMP"])
    runner = FakeRunner(
        files={di.FSTAB_PATH: existing_line},
        command_responses=[
            (lambda a: a[:1] == ["lvs"], FakeProc(0, "  pve   root  \n", "")),
        ],
    )
    di.ensure_volume(runner, vg_name="pve", lv_name="baseline_session_temp",
                      size="50G", label="SESSION_TEMP", mountpoint="/mnt/SESSION_TEMP")
    assert runner.files[di.FSTAB_PATH].count(existing_line) == 1


def test_ensure_volume_remounts_an_already_mounted_existing_volume_to_apply_options():
    """The real point of this feature: an already-mounted volume from
    before this fix must have its restrictive options actually applied,
    not just recorded in fstab for next boot."""
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["lvs"], FakeProc(0, "  pve   baseline_session_temp  \n", "")),
        (lambda a: a[:1] == ["mount"] and "-o" in a and "remount" not in a[2], FakeProc(32, "", "already mounted")),
    ])
    di.ensure_volume(runner, vg_name="pve", lv_name="baseline_session_temp",
                      size="50G", label="SESSION_TEMP", mountpoint="/mnt/SESSION_TEMP")
    remount_calls = [c for c in runner.calls if c[0] == "mount" and any("remount" in part for part in c)]
    assert remount_calls == [["mount", "-o", f"remount,{di.MOUNT_OPTIONS['SESSION_TEMP']}", "/mnt/SESSION_TEMP"]]


# --------------------------------------------------------------------------
# Adaptive volume sizing (decision record 73) - "there are no immutable
# volumes only reasons why things should change or not change them."
# The fixed BASELINE_VOLUMES sizes are a reasoned default, not a hard
# requirement - real available space always wins, scaled down rather
# than refused outright.
# --------------------------------------------------------------------------

def test_adaptive_single_size_gb_returns_desired_when_space_comfortably_covers_it():
    free_bytes = 500 * (1024 ** 3)
    assert di.adaptive_single_size_gb(free_bytes, 300) == 300


def test_adaptive_single_size_gb_scales_down_when_space_is_tight():
    free_bytes = 16 * (1024 ** 3)  # matches the real dev machine's actual free space
    result = di.adaptive_single_size_gb(free_bytes, 300)
    assert 0 < result < 300


def test_adaptive_single_size_gb_never_claims_the_full_safety_margin():
    free_bytes = 1 * (1024 ** 3)  # exactly the default 1GiB safety margin
    assert di.adaptive_single_size_gb(free_bytes, 300) == 0


def test_adaptive_single_size_gb_returns_zero_when_truly_out_of_space():
    assert di.adaptive_single_size_gb(0, 300) == 0


def test_compute_adaptive_plan_uses_defaults_when_space_comfortably_covers_everything():
    free_bytes = 1000 * (1024 ** 3)  # well over the 950G total default need (admin + personal)
    plan = di.compute_adaptive_plan(free_bytes)
    assert plan == {"BASELINE": 200, "USER_PERSISTENCE_ADMIN": 300, "USER_PERSISTENCE_PERSONAL": 300,
                     "INSTALLER_CACHE": 100, "SESSION_TEMP": 50}


def test_compute_adaptive_plan_scales_every_volume_down_proportionally_when_space_is_tight():
    free_bytes = 16 * (1024 ** 3)  # the real dev machine's actual free space - nowhere near 950G
    plan = di.compute_adaptive_plan(free_bytes)
    assert all(size_gb >= 1 for size_gb in plan.values())
    assert sum(plan.values()) <= 16
    # relative ordering preserved: each USER_PERSISTENCE_<PERSONA> (300G default) still gets
    # more than SESSION_TEMP (50G default)
    assert plan["USER_PERSISTENCE_ADMIN"] >= plan["SESSION_TEMP"]
    assert plan["USER_PERSISTENCE_PERSONAL"] >= plan["SESSION_TEMP"]


def test_compute_adaptive_plan_returns_zero_for_every_volume_when_truly_out_of_space():
    plan = di.compute_adaptive_plan(0)
    assert all(size_gb == 0 for size_gb in plan.values())


def test_ensure_baseline_volumes_adapts_sizes_instead_of_refusing_when_space_is_tight():
    """The real point of decision record 73: a real machine with only
    16GB free (this dev machine's own actual state) must still get
    working, adaptively-sized volumes, not a blanket refusal."""
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["vgs"], FakeProc(0, "17179869184\n", "")),  # 16GiB free
        (lambda a: a[:1] == ["lvs"], FakeProc(0, "  pve   root  \n", "")),
    ])
    results = di.ensure_baseline_volumes(runner, vg_name="pve")
    assert all(r.ok for r in results.values())
    lvcreate_calls = [c for c in runner.calls if c[0] == "lvcreate"]
    assert len(lvcreate_calls) == 5
    # none of the adapted sizes should be the old fixed defaults
    sizes_used = {c[c.index("-L") + 1] for c in lvcreate_calls}
    assert "300G" not in sizes_used
    assert "200G" not in sizes_used


def test_ensure_baseline_volumes_still_refuses_cleanly_when_truly_zero_space():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["vgs"], FakeProc(0, "0\n", "")),
    ])
    results = di.ensure_baseline_volumes(runner, vg_name="pve")
    assert all(r.ok is False for r in results.values())
    assert not any(c[0] == "lvcreate" for c in runner.calls)
