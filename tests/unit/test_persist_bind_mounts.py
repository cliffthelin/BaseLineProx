"""Unit tests for persist_bind_mounts.py - redirecting Baseline's own
credentials/state/logs onto USER via bind mounts, per
direct instruction ("All user data including credentials and config
and logs should go to the User Persistence partition"). Written after
the implementation existed but before any test did - real TDD
discipline still requires proving the implementation actually correct
before it counts as done, not just present. No real mount/fstab is
ever touched - the FakeRunner records everything.
"""
from fake_runner import FakeProc, FakeRunner

import persist_bind_mounts as pbm

MOUNTS_WITH_PERSISTENCE = "/dev/sdd2 /mnt/USER ext4 rw,relatime 0 0\n"
MOUNTS_WITHOUT_PERSISTENCE = "/dev/sdd1 / ext4 rw,relatime 0 0\n"


def test_user_mount_fstab_line():
    assert pbm.user_mount_fstab_line() == "LABEL=USER /mnt/USER ext4 defaults 0 2\n"


def test_bind_fstab_line():
    assert pbm.bind_fstab_line("/etc/baseline", "etc-baseline") == \
        "/mnt/USER/etc-baseline /etc/baseline none bind 0 0\n"


# -- is_mounted --------------------------------------------------------

def test_is_mounted_true_when_present_in_real_proc_mounts():
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITH_PERSISTENCE})
    assert pbm.is_mounted(runner, "/mnt/USER") is True


def test_is_mounted_false_when_absent():
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE})
    assert pbm.is_mounted(runner, "/mnt/USER") is False


def test_is_mounted_false_when_proc_mounts_unreadable():
    runner = FakeRunner()  # /proc/self/mounts not present at all
    assert pbm.is_mounted(runner, "/mnt/USER") is False


# -- is_mounted_read_write (work-queue item 26's hard exit condition) -----

def test_is_mounted_read_write_true_for_a_real_rw_mount():
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITH_PERSISTENCE})
    assert pbm.is_mounted_read_write(runner, "/mnt/USER") is True


def test_is_mounted_read_write_false_for_a_real_ro_mount():
    mounts = "/dev/sdd2 /mnt/USER ext4 ro,relatime 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts})
    assert pbm.is_mounted_read_write(runner, "/mnt/USER") is False


def test_is_mounted_read_write_false_when_not_mounted_at_all():
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE})
    assert pbm.is_mounted_read_write(runner, "/mnt/USER") is False


def test_is_mounted_read_write_false_when_proc_mounts_unreadable():
    runner = FakeRunner()
    assert pbm.is_mounted_read_write(runner, "/mnt/USER") is False


# -- ensure_user_volume_mounted -----------------------------------------

def test_ensure_user_volume_mounted_mounts_when_not_already():
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE})
    result = pbm.ensure_user_volume_mounted(runner)
    assert result.applied is True
    assert runner.calls[0] == ["mount", "LABEL=USER", "/mnt/USER"]


def test_ensure_user_volume_mounted_skips_mount_when_already_mounted():
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITH_PERSISTENCE})
    result = pbm.ensure_user_volume_mounted(runner)
    assert result.applied is True
    assert not any(c[:1] == ["mount"] for c in runner.calls)


def test_ensure_user_volume_mounted_appends_fstab_entry_when_missing():
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITH_PERSISTENCE, "/etc/fstab": "# existing\n"})
    pbm.ensure_user_volume_mounted(runner)
    assert "/etc/fstab" in runner.appends
    assert "LABEL=USER" in runner.files["/etc/fstab"]


def test_ensure_user_volume_mounted_never_duplicates_fstab_entry():
    existing = "# existing\n" + pbm.user_mount_fstab_line()
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITH_PERSISTENCE, "/etc/fstab": existing})
    pbm.ensure_user_volume_mounted(runner)
    assert runner.files["/etc/fstab"].count("LABEL=USER") == 1


def test_ensure_user_volume_mounted_reports_a_real_failure_when_every_fallback_is_exhausted():
    """Direct label mount fails, real discovery (blkid) finds no
    USER device anywhere, and there's no real local free
    space to self-install one either - the cascade is exhausted, not
    silently treated as success."""
    runner = FakeRunner(
        files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE},
        command_responses=[
            (lambda a: a[:1] == ["mount"] and "LABEL=USER" in a, FakeProc(1, "", "can't find LABEL=USER")),
            (lambda a: a[:1] == ["blkid"], FakeProc(2, "", "")),  # not found anywhere
            (lambda a: "vgs" in a, FakeProc(0, "0\n", "")),  # zero free space
        ],
    )
    result = pbm.ensure_user_volume_mounted(runner)
    assert result.applied is False


# -- real discovery + local self-install fallback (decision record 75) -
# "the drives are self installing systems... there are no immutable
# volumes only reasons why things should change or not change them."
# A missing external USER must never simply refuse - it is
# "the most important aspect to resolve," and gets resolved via real
# discovery first (never create a duplicate-labeled volume when one
# already exists elsewhere), then a local, adaptively-sized self-install
# only when nothing is found anywhere. -----------------------------

def test_discover_persistence_device_finds_a_real_device():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["blkid"], FakeProc(0, "/dev/sdb1\n", "")),
    ])
    assert pbm.discover_persistence_device(runner) == "/dev/sdb1"


def test_discover_persistence_device_returns_none_when_not_found():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["blkid"], FakeProc(2, "", "")),
    ])
    assert pbm.discover_persistence_device(runner) is None


def test_discover_persistence_device_returns_none_for_empty_output():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["blkid"], FakeProc(0, "", "")),
    ])
    assert pbm.discover_persistence_device(runner) is None


def test_ensure_user_volume_mounted_mounts_a_discovered_device_directly_rather_than_creating_a_duplicate():
    """A real USER-labeled device exists somewhere but
    mount-by-label didn't find it (e.g. not yet settled) - mount that
    exact device directly rather than self-installing a second,
    duplicate-labeled volume (the exact risk decision record 69 found)."""
    runner = FakeRunner(
        files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE},
        command_responses=[
            (lambda a: a[:1] == ["mount"] and "LABEL=USER" in a, FakeProc(1, "", "not found by label")),
            (lambda a: a[:1] == ["blkid"], FakeProc(0, "/dev/sdb1\n", "")),
            (lambda a: a[:1] == ["mount"] and a[1] == "/dev/sdb1", FakeProc(0, "", "")),
        ],
    )
    result = pbm.ensure_user_volume_mounted(runner)
    assert result.applied is True
    assert ["mount", "/dev/sdb1", "/mnt/USER"] in runner.calls
    # never attempted to create a new local volume when a real device was found
    assert not any(c[0] == "lvcreate" for c in runner.calls)


def test_ensure_user_volume_mounted_self_installs_locally_when_nothing_found_anywhere():
    runner = FakeRunner(
        files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE},
        command_responses=[
            (lambda a: a[:1] == ["mount"] and "LABEL=USER" in a, FakeProc(1, "", "not found")),
            (lambda a: a[:1] == ["blkid"], FakeProc(2, "", "")),
            (lambda a: "vgs" in a, FakeProc(0, "64424509440\n", "")),  # 60GiB free
            (lambda a: "lvs" in a, FakeProc(0, "  pve   root  \n", "")),
        ],
    )
    result = pbm.ensure_user_volume_mounted(runner)
    assert result.applied is True
    assert any(c[0] == "lvcreate" for c in runner.calls)
    lvcreate_call = next(c for c in runner.calls if c[0] == "lvcreate")
    assert "200G" not in lvcreate_call  # adaptively sized down from the 200G max, not the full ceiling


def test_ensure_user_volume_mounted_refuses_when_local_free_space_is_below_the_new_50gb_minimum():
    """Real, honest finding: this session's own real dev machine's `pve`
    VG has only ~16GiB genuinely free - below USER's own
    real (min_gb=50, max_gb=200) range (2026-09-29 sizing defaults), so
    the local self-install fallback now correctly refuses here instead
    of creating an undersized volume."""
    runner = FakeRunner(
        files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE},
        command_responses=[
            (lambda a: a[:1] == ["mount"] and "LABEL=USER" in a, FakeProc(1, "", "not found")),
            (lambda a: a[:1] == ["blkid"], FakeProc(2, "", "")),
            (lambda a: "vgs" in a, FakeProc(0, "17179869184\n", "")),  # 16GiB free, matches the real dev machine
            (lambda a: "lvs" in a, FakeProc(0, "  pve   root  \n", "")),
        ],
    )
    result = pbm.ensure_user_volume_mounted(runner)
    assert result.applied is False
    assert not any(c[0] == "lvcreate" for c in runner.calls)


def test_ensure_user_volume_mounted_refuses_cleanly_when_local_fallback_has_no_real_space():
    runner = FakeRunner(
        files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE},
        command_responses=[
            (lambda a: a[:1] == ["mount"] and "LABEL=USER" in a, FakeProc(1, "", "not found")),
            (lambda a: a[:1] == ["blkid"], FakeProc(2, "", "")),
            (lambda a: "vgs" in a, FakeProc(0, "0\n", "")),
        ],
    )
    result = pbm.ensure_user_volume_mounted(runner)
    assert result.applied is False
    assert not any(c[0] == "lvcreate" for c in runner.calls)


# -- ensure_redirect -------------------------------------------------------

def _mounted_runner(**files):
    return FakeRunner(files={"/proc/self/mounts": MOUNTS_WITH_PERSISTENCE, **files})


def test_ensure_redirect_migrates_existing_substrate_content_on_first_run():
    runner = _mounted_runner(**{
        "/etc/baseline/harness.env": "TOKEN=abc",
        "/etc/baseline/config.json": "{}",
    })
    result = pbm.ensure_redirect(runner, "/etc/baseline", "etc-baseline")
    assert result.applied is True
    mv_calls = [c for c in runner.calls if c[0] == "mv"]
    assert len(mv_calls) == 2
    assert {c[1] for c in mv_calls} == {"/etc/baseline/harness.env", "/etc/baseline/config.json"}
    assert all(c[2] == "/mnt/USER/etc-baseline/" for c in mv_calls)


def test_ensure_redirect_never_remigrates_once_the_persistence_side_exists():
    runner = _mounted_runner()
    runner.makedirs("/mnt/USER/etc-baseline")  # simulates a prior run already having migrated
    runner.makedirs("/etc/baseline")
    result = pbm.ensure_redirect(runner, "/etc/baseline", "etc-baseline")
    assert result.applied is True
    assert not any(c[0] == "mv" for c in runner.calls)


def test_ensure_redirect_creates_the_target_dir_if_missing_and_bind_mounts():
    runner = _mounted_runner()
    result = pbm.ensure_redirect(runner, "/etc/baseline", "etc-baseline")
    assert result.applied is True
    assert "/etc/baseline" in runner.dirs
    assert ["mount", "--bind", "/mnt/USER/etc-baseline", "/etc/baseline"] in runner.calls


def test_ensure_redirect_skips_bind_mount_when_already_bound():
    mounts = MOUNTS_WITH_PERSISTENCE + "/mnt/USER/etc-baseline /etc/baseline none rw,bind 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts})
    pbm.ensure_redirect(runner, "/etc/baseline", "etc-baseline")
    assert not any(c[:2] == ["mount", "--bind"] for c in runner.calls)


def test_ensure_redirect_never_duplicates_its_fstab_entry():
    existing = pbm.bind_fstab_line("/etc/baseline", "etc-baseline")
    runner = _mounted_runner(**{"/etc/fstab": existing})
    pbm.ensure_redirect(runner, "/etc/baseline", "etc-baseline")
    assert runner.files["/etc/fstab"].count("/etc/baseline") == 1


def test_ensure_redirect_reports_a_real_bind_mount_failure():
    runner = FakeRunner(
        files={"/proc/self/mounts": MOUNTS_WITH_PERSISTENCE},
        command_responses=[(lambda a: a[:2] == ["mount", "--bind"], FakeProc(1, "", "mount point does not exist"))],
    )
    result = pbm.ensure_redirect(runner, "/etc/baseline", "etc-baseline")
    assert result.applied is False
    assert "mount point does not exist" in result.detail


def test_ensure_redirect_refuses_when_persistence_partition_is_not_mounted():
    """The real gap this test proves: calling ensure_redirect() directly
    (not through ensure_all_redirects) must never silently create the
    persistence-side subdirectory and bind-mount onto it while
    /mnt/USER itself isn't actually mounted - that would
    write straight through to the disposable substrate, exactly the
    bug this module's own docstring says it prevents. The guarantee
    must hold inside ensure_redirect itself, not only in the sequencing
    of ensure_all_redirects, since nothing stops a future caller from
    invoking ensure_redirect on its own."""
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE})
    result = pbm.ensure_redirect(runner, "/etc/baseline", "etc-baseline")
    assert result.applied is False
    assert "not mounted" in result.detail.lower()
    # Nothing was created or mounted on the real substrate as a result.
    assert "/mnt/USER/etc-baseline" not in runner.dirs
    assert not any(c[0] in ("mv", "mount") for c in runner.calls)


# -- ensure_all_redirects ---------------------------------------------------

def test_ensure_all_redirects_runs_every_redirect_once_persistence_is_mounted():
    """The steady-state real case (persistence already mounted, as it
    is on every boot after the first). The "not yet mounted at all"
    case is covered separately below - a FakeRunner's /proc/self/mounts
    doesn't update itself just because a fake `mount` command
    "succeeded", the way the real kernel would, so that transition
    can't be honestly asserted end-to-end against this fake."""
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITH_PERSISTENCE})
    results = pbm.ensure_all_redirects(runner)
    assert len(results) == 1 + len(pbm.REDIRECT_PATHS)
    assert all(r.applied for r in results)
    for target_path in pbm.REDIRECT_PATHS:
        assert any(c[:2] == ["mount", "--bind"] and c[3] == target_path for c in runner.calls)


def test_main_returns_0_and_prints_each_result_when_everything_applies():
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITH_PERSISTENCE})
    printed = []
    code = pbm.main(runner=runner, print_fn=printed.append)
    assert code == 0
    redirect_lines = [line for line in printed if not line.startswith("[dep-")]
    assert len(redirect_lines) == 1 + len(pbm.REDIRECT_PATHS)
    assert all("[ok]" in line for line in redirect_lines)
    # Decision record 88: boot-phase dependency checks run and are
    # printed, but never change the return code either way.
    assert any(line.startswith("[dep-") for line in printed)


def test_main_returns_1_when_any_result_failed():
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE})  # persistence unmounted, no mount script configured to succeed
    code = pbm.main(runner=runner, print_fn=lambda *a: None)
    assert code == 1


def test_main_records_a_real_recovery_mode_entry_when_the_cascade_fails():
    """Work-queue item 26's real automatic entry point: a genuine
    cascade failure durably records that recovery mode is needed,
    without any separate poller having to notice it later."""
    import recovery_mode as rm
    runner = FakeRunner(
        files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE},
        command_responses=[
            (lambda a: a[:1] == ["mount"] and "LABEL=USER" in a, FakeProc(1, "", "no such partition")),
            (lambda a: a[:1] == ["blkid"], FakeProc(2, "", "")),
            (lambda a: "vgs" in a, FakeProc(0, "0\n", "")),
        ],
    )
    pbm.main(runner=runner, print_fn=lambda *a: None, now=1700000000.0)
    assert rm.is_active(runner) is True
    state = rm.read_state(runner)
    assert state["reason"] == "cascade_failed"
    assert state["entered_at"] == 1700000000.0


def test_main_never_enters_recovery_mode_when_the_cascade_succeeds():
    import recovery_mode as rm
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITH_PERSISTENCE})
    pbm.main(runner=runner, print_fn=lambda *a: None, now=1700000000.0)
    assert rm.is_active(runner) is False


def test_ensure_all_redirects_issues_the_real_mount_command_on_first_boot():
    """Proves the other half for real: when persistence isn't mounted
    yet, ensure_all_redirects's first step genuinely issues the real
    mount command - the actual redirect bind-mounts that depend on the
    kernel then reporting it mounted are exercised by
    ensure_redirect's own dedicated tests instead."""
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE})
    pbm.ensure_all_redirects(runner)
    assert ["mount", "LABEL=USER", "/mnt/USER"] in runner.calls


def test_ensure_all_redirects_stops_early_if_the_persistence_mount_fails():
    runner = FakeRunner(
        files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE},
        command_responses=[(lambda a: a[:1] == ["mount"], FakeProc(1, "", "no such partition"))],
    )
    results = pbm.ensure_all_redirects(runner)
    assert len(results) == 1
    assert results[0].applied is False
    # None of the three redirects were ever attempted.
    assert not any(c[0] == "mv" for c in runner.calls)


# -- persona-aware wiring (work-queue item 25, decision record 78) ---------

def test_user_label_for_defaults_to_legacy_singular_label():
    assert pbm.user_label_for() == "USER"
    assert pbm.user_label_for(None) == "USER"


def test_user_label_for_a_real_persona_uses_drive_installer_scheme():
    assert pbm.user_label_for("admin") == "USER_ADMIN"
    assert pbm.user_label_for("personal") == "USER_PERSONAL"


def test_user_mountpoint_for_defaults_to_legacy_mount_point():
    assert pbm.user_mountpoint_for() == "/mnt/USER"


def test_user_mountpoint_for_a_real_persona():
    assert pbm.user_mountpoint_for("admin") == "/mnt/USER_ADMIN"
    assert pbm.user_mountpoint_for("personal") == "/mnt/USER_PERSONAL"


def test_ensure_user_volume_mounted_with_a_persona_mounts_the_personas_own_label():
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE})
    result = pbm.ensure_user_volume_mounted(runner, persona="personal")
    assert result.applied is True
    assert runner.calls[0] == ["mount", "LABEL=USER_PERSONAL", "/mnt/USER_PERSONAL"]


def test_ensure_redirect_with_a_persona_binds_onto_the_personas_own_mountpoint():
    mounts = "/dev/sdd2 /mnt/USER_ADMIN ext4 rw,relatime 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts})
    result = pbm.ensure_redirect(runner, "/etc/baseline", "etc-baseline", persona="admin")
    assert result.applied is True
    assert ["mount", "--bind", "/mnt/USER_ADMIN/etc-baseline", "/etc/baseline"] in runner.calls


def test_ensure_all_redirects_with_a_persona_never_touches_the_legacy_label():
    mounts = "/dev/sdd2 /mnt/USER_PERSONAL ext4 rw,relatime 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts})
    results = pbm.ensure_all_redirects(runner, persona="personal")
    assert all(r.applied for r in results)
    assert not any("LABEL=USER " in " ".join(c) or c == ["mount", "LABEL=USER", "/mnt/USER"]
                   for c in runner.calls)


# -- unmount_user_volume / unmount_redirect / unmount_all_redirects --------

def test_unmount_user_volume_is_a_noop_success_when_already_unmounted():
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE})
    result = pbm.unmount_user_volume(runner)
    assert result.applied is True
    assert not any(c[:1] == ["umount"] for c in runner.calls)


def test_unmount_user_volume_runs_real_umount_when_mounted():
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITH_PERSISTENCE})
    result = pbm.unmount_user_volume(runner)
    assert result.applied is True
    assert ["umount", "/mnt/USER"] in runner.calls


def test_unmount_user_volume_reports_a_real_failure():
    runner = FakeRunner(
        files={"/proc/self/mounts": MOUNTS_WITH_PERSISTENCE},
        command_responses=[(lambda a: a[:1] == ["umount"], FakeProc(1, "", "target is busy"))],
    )
    result = pbm.unmount_user_volume(runner)
    assert result.applied is False
    assert "target is busy" in result.detail


def test_unmount_redirect_is_a_noop_success_when_not_bound():
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITH_PERSISTENCE})
    result = pbm.unmount_redirect(runner, "/etc/baseline")
    assert result.applied is True
    assert not any(c[:1] == ["umount"] for c in runner.calls)


def test_unmount_redirect_runs_real_umount_when_bound():
    mounts = MOUNTS_WITH_PERSISTENCE + "/mnt/USER/etc-baseline /etc/baseline none rw,bind 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts})
    result = pbm.unmount_redirect(runner, "/etc/baseline")
    assert result.applied is True
    assert ["umount", "/etc/baseline"] in runner.calls


def test_unmount_all_redirects_unbinds_every_redirect_before_the_persistence_volume():
    mounts = (MOUNTS_WITH_PERSISTENCE
              + "/mnt/USER/etc-baseline /etc/baseline none rw,bind 0 0\n"
              + "/mnt/USER/var-lib-baseline /var/lib/baseline none rw,bind 0 0\n"
              + "/mnt/USER/var-log-baseline /var/log/baseline none rw,bind 0 0\n")
    runner = FakeRunner(files={"/proc/self/mounts": mounts})
    results = pbm.unmount_all_redirects(runner)
    assert all(r.applied for r in results)
    assert len(results) == 1 + len(pbm.REDIRECT_PATHS)
    umount_calls = [c[1] for c in runner.calls if c[:1] == ["umount"]]
    # every redirect target unbound before the persistence mountpoint itself
    assert umount_calls.index("/mnt/USER") == len(umount_calls) - 1


# -- get_active_persona / set_active_persona / switch_active_persona -------

def test_get_active_persona_defaults_when_no_marker_exists():
    runner = FakeRunner()
    assert pbm.get_active_persona(runner) == "admin"


def test_get_active_persona_reads_a_real_marker():
    runner = FakeRunner(files={pbm.ACTIVE_PERSONA_MARKER_PATH: "personal"})
    assert pbm.get_active_persona(runner) == "personal"


def test_set_active_persona_writes_a_real_marker_on_baseline():
    runner = FakeRunner()
    pbm.set_active_persona(runner, "personal")
    assert runner.files[pbm.ACTIVE_PERSONA_MARKER_PATH] == "personal"


def test_switch_active_persona_refuses_without_a_proven_credential():
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE})
    result = pbm.switch_active_persona(runner, to_persona="personal", credential_ok=False)
    assert result.applied is False
    assert not any(c[:1] in (["mount"], ["umount"]) for c in runner.calls)


def test_switch_active_persona_is_idempotent_when_already_active():
    mounts = "/dev/sdd2 /mnt/USER_ADMIN ext4 rw,relatime 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts, pbm.ACTIVE_PERSONA_MARKER_PATH: "admin"})
    result = pbm.switch_active_persona(runner, to_persona="admin", credential_ok=True)
    assert result.applied is True
    assert not any(c[:1] == ["umount"] for c in runner.calls)


def test_switch_active_persona_unmounts_current_and_issues_the_real_mount_command_for_the_new_one():
    """A FakeRunner's /proc/self/mounts doesn't update itself just
    because a fake `umount`/`mount` command "succeeded", the same
    honest limitation this module's own pre-existing tests already
    document for `ensure_all_redirects` - so this proves the real
    commands are issued, in the right order, not the full end-to-end
    mounted-and-bound outcome (covered separately below against an
    already-steady-state fake)."""
    mounts = "/dev/sdd2 /mnt/USER_ADMIN ext4 rw,relatime 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts, pbm.ACTIVE_PERSONA_MARKER_PATH: "admin"})
    pbm.switch_active_persona(runner, to_persona="personal", credential_ok=True)
    assert ["umount", "/mnt/USER_ADMIN"] in runner.calls
    assert ["mount", "LABEL=USER_PERSONAL", "/mnt/USER_PERSONAL"] in runner.calls
    # the unmount happened before the new mount
    assert runner.calls.index(["umount", "/mnt/USER_ADMIN"]) < \
        runner.calls.index(["mount", "LABEL=USER_PERSONAL", "/mnt/USER_PERSONAL"])


def test_switch_active_persona_succeeds_and_updates_the_marker_once_the_new_persona_is_actually_mounted():
    """The steady-state real case, matching
    `test_ensure_all_redirects_runs_every_redirect_once_persistence_is_mounted`'s
    own precedent: once the target persona's volume is genuinely
    mounted, the switch's redirect-rebinding half succeeds for real and
    the active-persona marker is durably updated."""
    mounts = "/dev/sdd2 /mnt/USER_PERSONAL ext4 rw,relatime 0 0\n"
    runner = FakeRunner(files={"/proc/self/mounts": mounts, pbm.ACTIVE_PERSONA_MARKER_PATH: "admin"})
    result = pbm.switch_active_persona(runner, to_persona="personal", credential_ok=True)
    assert result.applied is True
    assert runner.files[pbm.ACTIVE_PERSONA_MARKER_PATH] == "personal"
    for target_path in pbm.REDIRECT_PATHS:
        assert any(c[:2] == ["mount", "--bind"] and c[3] == target_path for c in runner.calls)


def test_switch_active_persona_reports_a_real_unmount_failure_and_never_mounts_the_new_one():
    mounts = "/dev/sdd2 /mnt/USER_ADMIN ext4 rw,relatime 0 0\n"
    runner = FakeRunner(
        files={"/proc/self/mounts": mounts, pbm.ACTIVE_PERSONA_MARKER_PATH: "admin"},
        command_responses=[(lambda a: a[:1] == ["umount"], FakeProc(1, "", "target is busy"))],
    )
    result = pbm.switch_active_persona(runner, to_persona="personal", credential_ok=True)
    assert result.applied is False
    assert "target is busy" in result.detail
    assert not any(c[:1] == ["mount"] and "PERSONAL" in c[1] for c in runner.calls)
    assert runner.files[pbm.ACTIVE_PERSONA_MARKER_PATH] == "admin"


def test_a_persona_volume_mounts_by_a_label_that_actually_fits_on_disk():
    """Before the rename, the code mounted LABEL=USER_PERSISTENCE_ADMIN,
    but ext4 truncates labels at 16 so the disk said USER_PERSISTENCE -
    the mount could never match, and the legacy path matched BOTH
    persona volumes. The current labels fit, so the label mounted is the
    label written."""
    import drive_installer as di
    for persona in di.DEFAULT_PERSONAS:
        label = pbm.user_label_for(persona)
        assert len(label) <= 16
        assert f"LABEL={label} " in pbm.user_mount_fstab_line(persona)
