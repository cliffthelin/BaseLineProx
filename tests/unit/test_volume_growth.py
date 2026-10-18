"""Volumes grow only when used and needed: pure planning arithmetic and the exact command; the real LVM growth is checked in the rehearsal VM."""
import pytest

import volume_growth as vg

GIB = 1024 ** 3


def row(label, size, used, max_gib=200):
    return {"label": label, "name": label.lower(), "size_bytes": size * GIB, "used_bytes": int(used * GIB), "max_gib": max_gib}


def test_a_volume_that_is_not_nearly_full_is_left_alone():
    assert vg.plan([row("USER_ADMIN", 10, 3), row("BASELINE", 1, 0.5)], 100 * GIB) == []


def test_a_nearly_full_volume_grows_to_headroom_over_what_it_holds_and_at_least_one_gib():
    [item] = vg.plan([row("INSTALLER_CACHE", 10, 9)], 100 * GIB)
    assert item == {"label": "INSTALLER_CACHE", "name": "installer_cache", "add_gib": 4}          # 9 GiB used * 1.5 = 13.5 -> 14
    [small] = vg.plan([row("USER_ADMIN", 1, 0.9)], 100 * GIB)
    assert small["add_gib"] >= 1


def test_growth_never_takes_the_last_gib_of_the_group_and_serves_the_fullest_first():
    items = vg.plan([row("A_ROLE", 10, 8.5), row("B_ROLE", 10, 9.9)], 6 * GIB)         # 5 GiB spendable
    assert [i["label"] for i in items] == ["B_ROLE", "A_ROLE"] or [i["label"] for i in items] == ["B_ROLE"]
    assert sum(i["add_gib"] for i in items) <= 5
    assert vg.plan([row("X", 10, 9.9)], 1 * GIB) == []


def test_growth_stops_at_a_roles_own_ceiling():
    [item] = vg.plan([row("SESSION_TEMP", 49, 48, max_gib=50)], 100 * GIB)
    assert item["add_gib"] == 1
    assert vg.plan([row("SESSION_TEMP", 50, 49.9, max_gib=50)], 100 * GIB) == []


def test_room_needed_extends_for_a_large_copy_and_refuses_one_that_cannot_finish():
    cache = row("INSTALLER_CACHE", 6, 5)
    assert vg.room_needed(cache, GIB // 2, 100 * GIB) is None
    assert vg.room_needed(cache, 28 * GIB, 100 * GIB) == {"label": "INSTALLER_CACHE", "name": "installer_cache", "add_gib": 30}   # 27 GiB short, plus ext4 overhead
    with pytest.raises(vg.GrowthError, match="unallocated"):
        vg.room_needed(cache, 28 * GIB, 20 * GIB)
    with pytest.raises(vg.GrowthError, match="ceiling"):
        vg.room_needed(row("INSTALLER_CACHE", 6, 5, max_gib=10), 28 * GIB, 100 * GIB)


def test_the_extension_command_resizes_the_volume_and_its_filesystem_together_and_only_ever_grows():
    assert vg.lvextend_argv("pve", "baseline_installer_cache", 3) == ["lvextend", "-L", "+3G", "-r", "/dev/pve/baseline_installer_cache"]
    for bad in (0, -1, 1.5, "2"):
        with pytest.raises(vg.GrowthError):
            vg.lvextend_argv("pve", "x", bad)


def test_the_running_roots_group_is_chosen_when_another_drive_also_has_a_root_volume():
    """Two Baseline drives attached: both groups hold a `root`. The running one is the group behind the mounted root."""
    import json
    from fake_runner import FakeProc, FakeRunner

    class Runner(FakeRunner):
        def run(self, argv, timeout=10):
            self.calls.append(list(argv))
            if argv[0] == "findmnt":
                return FakeProc(0, "/dev/mapper/baseline_aaaa-root\n", "")
            if argv[0] == "lvs" and argv[-1] == "/dev/mapper/baseline_aaaa-root":
                return FakeProc(0, json.dumps({"report": [{"lv": [{"vg_name": "baseline_aaaa", "lv_name": "root"}]}]}), "")
            return FakeProc(1, "", "unexpected")

    assert vg.volume_group(Runner()) == "baseline_aaaa"


def test_room_is_computed_from_what_the_filesystem_reports_available_with_its_overhead():
    """The volume was 'big enough' by size minus used, but ext4 reports less available: the copy then failed for a few hundred MiB."""
    cache = dict(row("INSTALLER_CACHE", 10, 6), available_bytes=3 * GIB)          # size - used says 4 GiB; the filesystem says 3
    item = vg.room_needed(cache, 5 * GIB, 100 * GIB)
    assert item["add_gib"] == 3                                                  # (5 - 3) * 1.08 = 2.16 -> 3
    assert vg.room_needed(dict(cache, available_bytes=6 * GIB), 5 * GIB, 100 * GIB) is None


def test_collect_gives_every_role_the_whole_group_as_its_ceiling():
    import json
    import subprocess
    import drive_installer as di

    name, _, table_ceiling, label, mountpoint = di.baseline_volumes_for()[0]

    class R:
        def run(self, argv, timeout=None):
            if argv[0] == "lvs":
                out = {"report": [{"lv": [{"lv_name": name, "lv_size": str(10 * GIB)}]}]}
            elif argv[0] == "vgs":
                out = {"report": [{"vg": [{"vg_free": str(90 * GIB)}]}]}
            else:
                return subprocess.CompletedProcess(argv, 0, "Used Avail Size\n9 1 10\n", "")
            return subprocess.CompletedProcess(argv, 0, json.dumps(out), "")

    monkey = vg.di
    original = monkey.parse_df_output
    monkey.parse_df_output = lambda text: {"used_bytes": 9 * GIB, "available_bytes": GIB}
    try:
        rows, _ = vg.collect(R(), "vg")
    finally:
        monkey.parse_df_output = original
    assert rows and rows[0]["max_gib"] == 100
