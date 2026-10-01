"""Tests for baseline_drive_layout.py: lay Baseline's defined volumes
(drive_installer.SHARED_VOLUMES + persona volumes) onto a plain-GPT Baseline drive
drive, the way decision record 46 did, with no LVM and no root. Pure: commands
go through an injected runner and validation through an injected validator."""
import pytest

import baseline_drive_layout as cl
import drive_guard as dg
import drive_installer as di

SIZE = 512_110_190_592
DEV = "/dev/sdd"
GUID = "8afe8468-ea73-4944-8842-0cbbe4a82d16"


@pytest.fixture(autouse=True)
def _blank_drive(monkeypatch):
    """The drive being laid out is blank, so the data-protection check passes."""
    monkeypatch.setattr(dg, "_default_run", lambda argv: (0, f"sdd disk  {GUID} \n"))


def test_plan_uses_baselines_own_volumes_and_adaptive_sizes():
    plan = cl.plan_partitions(SIZE)
    want = di.compute_adaptive_plan(SIZE - di.DEFAULT_SAFETY_MARGIN_BYTES)
    assert [p["label"] for p in plan] == [v[3] for v in di.BASELINE_VOLUMES]
    assert {p["label"]: p["size_gb"] for p in plan} == want


def test_plan_carries_mountpoints_and_mount_options_from_baseline():
    by = {p["label"]: p for p in cl.plan_partitions(SIZE)}
    assert by["INSTALLER_CACHE"]["mountpoint"] == "/mnt/INSTALLER_CACHE"
    assert "noexec" in by["INSTALLER_CACHE"]["options"]
    assert "noexec" not in by["BASELINE"]["options"]


def test_partitions_are_aligned_ordered_and_fit_on_the_drive():
    plan = cl.plan_partitions(SIZE)
    prev_end = 0
    for p in plan:
        assert p["start_sector"] % 2048 == 0
        assert p["start_sector"] > prev_end
        prev_end = p["start_sector"] + p["size_gb"] * 1024**3 // 512 - 1
    assert prev_end * 512 < SIZE


def test_a_drive_too_small_for_every_minimum_is_refused():
    with pytest.raises(ValueError):
        cl.plan_partitions(20 * 1024**3)


def test_ext4_labels_fit_16_chars_and_identity_is_the_full_partition_name():
    for p in cl.plan_partitions(SIZE):
        assert len(p["fs_label"]) <= 16
        assert p["partname"] == p["label"]


def test_sgdisk_argv_targets_only_the_device_and_names_each_partition():
    plan = cl.plan_partitions(SIZE)
    argv = cl.sgdisk_argv(DEV, plan)
    assert argv[0] == "sgdisk" and argv[-1] == DEV
    assert argv.count("-n") == len(plan) == argv.count("-c")
    assert f"1:{plan[0]['start_sector']}:+{plan[0]['size_gb']}G" in argv


def test_mkfs_argv_formats_by_byte_offset_when_the_kernel_has_not_reread():
    p = cl.plan_partitions(SIZE)[1]
    argv = cl.mkfs_argv(DEV, p)
    assert argv[:2] == ["mkfs.ext4", "-F"] and "-L" in argv
    assert f"offset={p['start_sector'] * 512}" in argv[argv.index("-E") + 1]
    assert argv[-2] == DEV and argv[-1] == f"{p['size_gb'] * 1024 * 1024}k"


class Cmd:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def run(self, argv):
        self.calls.append(list(argv))
        return (1, "", "boom") if self.fail_on and argv[0] == self.fail_on else (0, "", "")


def ok_validator(path, **kw):
    return {"path": path, "serial": "X", "size_bytes": SIZE}


def test_apply_validates_first_then_wipes_partitions_and_formats_each_volume():
    cmd = Cmd()
    plan = cl.apply(cmd, DEV, validate=ok_validator)
    names = [c[0] for c in cmd.calls]
    assert names[0] == "wipefs" and names[1] == "sgdisk"
    assert names.count("mkfs.ext4") == len(plan)


def test_apply_runs_nothing_when_validation_refuses():
    def refuse(path, **kw):
        raise cl.PhysicalDeviceSafetyError("boot device")

    cmd = Cmd()
    with pytest.raises(cl.PhysicalDeviceSafetyError):
        cl.apply(cmd, DEV, validate=refuse)
    assert cmd.calls == []


def test_apply_stops_at_the_first_failing_command():
    cmd = Cmd(fail_on="sgdisk")
    with pytest.raises(cl.LayoutError):
        cl.apply(cmd, DEV, validate=ok_validator)
    assert [c[0] for c in cmd.calls] == ["wipefs", "sgdisk"]


def test_agent_index_names_the_real_volume_and_its_baseline_rules():
    by = {p["label"]: p for p in cl.plan_partitions(SIZE)}
    text = cl.agent_index(by["INSTALLER_CACHE"], serial="MD89N41071210AP4E")
    assert "INSTALLER_CACHE" in text and "/mnt/INSTALLER_CACHE" in text
    assert "noexec" in text and "MD89N41071210AP4E" in text
    assert "never by kernel letter" in text


def test_adding_appdata_does_not_renumber_existing_partitions():
    """Real hazard: interleaving AppData per persona moved
    USER_PERSONAL from partition 6 to 7. The real carrier
    already has partitions 1-6 laid out, so re-applying a renumbered plan
    would treat the personal persona's partition as AppData. New volumes
    append; existing numbers never move."""
    by_label = {p["label"]: p["number"] for p in cl.plan_partitions(476 * 1024**3)}
    assert by_label["BASELINE"] == 1
    assert by_label["INSTALLER_CACHE"] == 2
    assert by_label["SESSION_TEMP"] == 3
    assert by_label["SUBSTRATE"] == 4
    assert by_label["USER_ADMIN"] == 5
    assert by_label["USER_PERSONAL"] == 6
    assert by_label["APPDATA_ADMIN"] == 7
    assert by_label["APPDATA_PERSONAL"] == 8


def test_every_planned_partition_has_a_role_including_appdata():
    """_role() raised KeyError for APPDATA_*, so agentIndex.md could not
    be generated for those partitions."""
    for p in cl.plan_partitions(476 * 1024**3):
        assert cl.agent_index(p, serial="TESTSERIAL").strip()


def test_appdata_labels_fit_ext4_for_the_default_personas():
    for p in cl.plan_partitions(476 * 1024**3):
        if p["label"].startswith("APPDATA_"):
            assert p["fs_label"] == p["label"], f"{p['label']} truncates"


def test_legacy_relabel_plan_renames_old_partitions_in_place():
    current = [(1, "BASELINE"), (2, "INSTALLER_CACHE"), (3, "SESSION_TEMP"),
               (4, "SUBSTRATE_PERSISTENCE"), (5, "USER_PERSISTENCE_ADMIN"),
               (6, "USER_PERSISTENCE_PERSONAL")]
    plan = cl.legacy_relabel_plan("/dev/sdd", current)
    assert ["sgdisk", "-c", "4:SUBSTRATE", "/dev/sdd"] in plan
    assert ["e2label", "/dev/sdd5", "USER_ADMIN"] in plan
    assert ["e2label", "/dev/sdd6", "USER_PERSONAL"] in plan
    assert len(plan) == 6                      # 3 partitions x (GPT name + ext4 label)


def test_legacy_relabel_plan_is_metadata_only():
    """No step may reformat, repartition or move data."""
    current = [(5, "USER_PERSISTENCE_ADMIN")]
    for argv in cl.legacy_relabel_plan("/dev/sdd", current):
        assert argv[0] in ("sgdisk", "e2label")
        assert "-n" not in argv and "-d" not in argv and "-o" not in argv and "-Z" not in argv


def test_legacy_relabel_plan_is_empty_for_a_current_drive():
    assert cl.legacy_relabel_plan("/dev/sdd", [(5, "USER_ADMIN"), (1, "BASELINE")]) == []


def test_relabel_uses_the_nvme_partition_naming():
    plan = cl.legacy_relabel_plan("/dev/nvme0n1", [(5, "USER_PERSISTENCE_ADMIN")])
    assert ["e2label", "/dev/nvme0n1p5", "USER_ADMIN"] in plan


def test_apply_refuses_a_drive_with_data_and_no_installer_uuid_and_runs_nothing(monkeypatch):
    monkeypatch.setattr(dg, "_default_run", lambda argv: (0, f"sdd disk  {GUID} \nsdd1 part ntfs  TV\n"))
    cmd = Cmd()
    with pytest.raises(cl.LayoutError, match="not the Baseline drive"):
        cl.apply(cmd, DEV, validate=ok_validator)
    assert cmd.calls == []


def test_apply_lays_out_a_drive_with_data_that_the_installer_created(monkeypatch):
    monkeypatch.setattr(dg, "_default_run", lambda argv: (0, f"sdd disk  {GUID} \nsdd1 part ext4  BASELINE\n"))
    dg.register_installer_uuid(GUID, serial="MD89N41071210AP4E")
    cmd = Cmd()
    assert cl.apply(cmd, DEV, validate=ok_validator)
    assert cmd.calls and cmd.calls[0][0] == "wipefs"


def test_apply_refuses_baseline_labelled_data_without_an_installer_uuid(monkeypatch):
    monkeypatch.setattr(dg, "_default_run", lambda argv: (0, f"sdd disk  {GUID} \nsdd1 part ext4  BASELINE\n"))
    cmd = Cmd()
    with pytest.raises(cl.LayoutError, match="installer"):
        cl.apply(cmd, DEV, validate=ok_validator)
    assert cmd.calls == []
