"""Unit tests for persist_bind_mounts.py - redirecting Baseline's own
credentials/state/logs onto USER_PERSISTENCE via bind mounts, per
direct instruction ("All user data including credentials and config
and logs should go to the User Persistence partition"). Written after
the implementation existed but before any test did - real TDD
discipline still requires proving the implementation actually correct
before it counts as done, not just present. No real mount/fstab is
ever touched - the FakeRunner records everything.
"""
from fake_runner import FakeProc, FakeRunner

import persist_bind_mounts as pbm

MOUNTS_WITH_PERSISTENCE = "/dev/sdd2 /mnt/USER_PERSISTENCE ext4 rw,relatime 0 0\n"
MOUNTS_WITHOUT_PERSISTENCE = "/dev/sdd1 / ext4 rw,relatime 0 0\n"


def test_persistence_mount_fstab_line():
    assert pbm.persistence_mount_fstab_line() == "LABEL=USER_PERSISTENCE /mnt/USER_PERSISTENCE ext4 defaults 0 2\n"


def test_bind_fstab_line():
    assert pbm.bind_fstab_line("/etc/baseline", "etc-baseline") == \
        "/mnt/USER_PERSISTENCE/etc-baseline /etc/baseline none bind 0 0\n"


# -- is_mounted --------------------------------------------------------

def test_is_mounted_true_when_present_in_real_proc_mounts():
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITH_PERSISTENCE})
    assert pbm.is_mounted(runner, "/mnt/USER_PERSISTENCE") is True


def test_is_mounted_false_when_absent():
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE})
    assert pbm.is_mounted(runner, "/mnt/USER_PERSISTENCE") is False


def test_is_mounted_false_when_proc_mounts_unreadable():
    runner = FakeRunner()  # /proc/self/mounts not present at all
    assert pbm.is_mounted(runner, "/mnt/USER_PERSISTENCE") is False


# -- ensure_persistence_mounted -----------------------------------------

def test_ensure_persistence_mounted_mounts_when_not_already():
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE})
    result = pbm.ensure_persistence_mounted(runner)
    assert result.applied is True
    assert runner.calls[0] == ["mount", "LABEL=USER_PERSISTENCE", "/mnt/USER_PERSISTENCE"]


def test_ensure_persistence_mounted_skips_mount_when_already_mounted():
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITH_PERSISTENCE})
    result = pbm.ensure_persistence_mounted(runner)
    assert result.applied is True
    assert not any(c[:1] == ["mount"] for c in runner.calls)


def test_ensure_persistence_mounted_appends_fstab_entry_when_missing():
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITH_PERSISTENCE, "/etc/fstab": "# existing\n"})
    pbm.ensure_persistence_mounted(runner)
    assert "/etc/fstab" in runner.appends
    assert "LABEL=USER_PERSISTENCE" in runner.files["/etc/fstab"]


def test_ensure_persistence_mounted_never_duplicates_fstab_entry():
    existing = "# existing\n" + pbm.persistence_mount_fstab_line()
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITH_PERSISTENCE, "/etc/fstab": existing})
    pbm.ensure_persistence_mounted(runner)
    assert runner.files["/etc/fstab"].count("LABEL=USER_PERSISTENCE") == 1


def test_ensure_persistence_mounted_reports_a_real_failure_when_every_fallback_is_exhausted():
    """Direct label mount fails, real discovery (blkid) finds no
    USER_PERSISTENCE device anywhere, and there's no real local free
    space to self-install one either - the cascade is exhausted, not
    silently treated as success."""
    runner = FakeRunner(
        files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE},
        command_responses=[
            (lambda a: a[:1] == ["mount"] and "LABEL=USER_PERSISTENCE" in a, FakeProc(1, "", "can't find LABEL=USER_PERSISTENCE")),
            (lambda a: a[:1] == ["blkid"], FakeProc(2, "", "")),  # not found anywhere
            (lambda a: a[:1] == ["vgs"], FakeProc(0, "0\n", "")),  # zero free space
        ],
    )
    result = pbm.ensure_persistence_mounted(runner)
    assert result.applied is False


# -- real discovery + local self-install fallback (decision record 75) -
# "the drives are self installing systems... there are no immutable
# volumes only reasons why things should change or not change them."
# A missing external USER_PERSISTENCE must never simply refuse - it is
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


def test_ensure_persistence_mounted_mounts_a_discovered_device_directly_rather_than_creating_a_duplicate():
    """A real USER_PERSISTENCE-labeled device exists somewhere but
    mount-by-label didn't find it (e.g. not yet settled) - mount that
    exact device directly rather than self-installing a second,
    duplicate-labeled volume (the exact risk decision record 69 found)."""
    runner = FakeRunner(
        files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE},
        command_responses=[
            (lambda a: a[:1] == ["mount"] and "LABEL=USER_PERSISTENCE" in a, FakeProc(1, "", "not found by label")),
            (lambda a: a[:1] == ["blkid"], FakeProc(0, "/dev/sdb1\n", "")),
            (lambda a: a[:1] == ["mount"] and a[1] == "/dev/sdb1", FakeProc(0, "", "")),
        ],
    )
    result = pbm.ensure_persistence_mounted(runner)
    assert result.applied is True
    assert ["mount", "/dev/sdb1", "/mnt/USER_PERSISTENCE"] in runner.calls
    # never attempted to create a new local volume when a real device was found
    assert not any(c[0] == "lvcreate" for c in runner.calls)


def test_ensure_persistence_mounted_self_installs_locally_when_nothing_found_anywhere():
    runner = FakeRunner(
        files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE},
        command_responses=[
            (lambda a: a[:1] == ["mount"] and "LABEL=USER_PERSISTENCE" in a, FakeProc(1, "", "not found")),
            (lambda a: a[:1] == ["blkid"], FakeProc(2, "", "")),
            (lambda a: a[:1] == ["vgs"], FakeProc(0, "17179869184\n", "")),  # 16GiB free, matches the real dev machine
            (lambda a: a[:1] == ["lvs"], FakeProc(0, "  pve   root  \n", "")),
        ],
    )
    result = pbm.ensure_persistence_mounted(runner)
    assert result.applied is True
    assert any(c[0] == "lvcreate" for c in runner.calls)
    lvcreate_call = next(c for c in runner.calls if c[0] == "lvcreate")
    assert "300G" not in lvcreate_call  # adaptively sized down, not the full default


def test_ensure_persistence_mounted_refuses_cleanly_when_local_fallback_has_no_real_space():
    runner = FakeRunner(
        files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE},
        command_responses=[
            (lambda a: a[:1] == ["mount"] and "LABEL=USER_PERSISTENCE" in a, FakeProc(1, "", "not found")),
            (lambda a: a[:1] == ["blkid"], FakeProc(2, "", "")),
            (lambda a: a[:1] == ["vgs"], FakeProc(0, "0\n", "")),
        ],
    )
    result = pbm.ensure_persistence_mounted(runner)
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
    assert all(c[2] == "/mnt/USER_PERSISTENCE/etc-baseline/" for c in mv_calls)


def test_ensure_redirect_never_remigrates_once_the_persistence_side_exists():
    runner = _mounted_runner()
    runner.makedirs("/mnt/USER_PERSISTENCE/etc-baseline")  # simulates a prior run already having migrated
    runner.makedirs("/etc/baseline")
    result = pbm.ensure_redirect(runner, "/etc/baseline", "etc-baseline")
    assert result.applied is True
    assert not any(c[0] == "mv" for c in runner.calls)


def test_ensure_redirect_creates_the_target_dir_if_missing_and_bind_mounts():
    runner = _mounted_runner()
    result = pbm.ensure_redirect(runner, "/etc/baseline", "etc-baseline")
    assert result.applied is True
    assert "/etc/baseline" in runner.dirs
    assert ["mount", "--bind", "/mnt/USER_PERSISTENCE/etc-baseline", "/etc/baseline"] in runner.calls


def test_ensure_redirect_skips_bind_mount_when_already_bound():
    mounts = MOUNTS_WITH_PERSISTENCE + "/mnt/USER_PERSISTENCE/etc-baseline /etc/baseline none rw,bind 0 0\n"
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
    /mnt/USER_PERSISTENCE itself isn't actually mounted - that would
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
    assert "/mnt/USER_PERSISTENCE/etc-baseline" not in runner.dirs
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
    assert len(printed) == 1 + len(pbm.REDIRECT_PATHS)
    assert all("[ok]" in line for line in printed)


def test_main_returns_1_when_any_result_failed():
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE})  # persistence unmounted, no mount script configured to succeed
    code = pbm.main(runner=runner, print_fn=lambda *a: None)
    assert code == 1


def test_ensure_all_redirects_issues_the_real_mount_command_on_first_boot():
    """Proves the other half for real: when persistence isn't mounted
    yet, ensure_all_redirects's first step genuinely issues the real
    mount command - the actual redirect bind-mounts that depend on the
    kernel then reporting it mounted are exercised by
    ensure_redirect's own dedicated tests instead."""
    runner = FakeRunner(files={"/proc/self/mounts": MOUNTS_WITHOUT_PERSISTENCE})
    pbm.ensure_all_redirects(runner)
    assert ["mount", "LABEL=USER_PERSISTENCE", "/mnt/USER_PERSISTENCE"] in runner.calls


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
