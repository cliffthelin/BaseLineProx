"""Populated-drive protection plus the per-installer-lane development lock (DR300).

A drive "has data" if it has any partition, filesystem, LVM or encrypted volume; a blank drive, or one with an
empty partition table, has none; a drive whose state cannot be read is treated as having data. Normally, a drive
counts as installer-made only if its GPT disk GUID is one the installer generated and registered. Each installer
lane may act only on its exact locked serial; the other lane's drive remains protected. No physical device is opened
by these tests."""
import inspect

import pytest

import drive_admin as da
import drive_guard as dg
import registry

GUID = "8afe8468-ea73-4944-8842-0cbbe4a82d16"
BLANK = f"sdb disk  {GUID} \n"
DATA = (f"sdb disk  {GUID} \nsdb1 part ntfs  TV\n")
BASELINE_DRIVE = (f"sdb disk  {GUID} \nsdb1 part ext4  BASELINE\nsdb2 part ext4  INSTALLER_CACHE\nsdb3 part ext4  SESSION_TEMP\n"
                  "sdb4 part ext4  SUBSTRATE\nsdb5 part ext4  USER_ADMIN\nsdb6 part ext4  USER_PERSONAL\n")


def runner(output, rc=0):
    calls = []

    def run(argv):
        calls.append(list(argv))
        if "SERIAL" in argv:
            return 0, "UNLOCKED-TEST-DISK\n"
        return rc, output
    run.calls = calls
    return run


# --- what counts as data ----------------------------------------------------------

def test_a_blank_disk_has_no_data():
    state = dg.read_drive_state("/dev/sdb", run=runner(BLANK))
    assert state.known and state.has_data is False and state.ptuuid == GUID


def test_an_empty_partition_table_is_not_data():
    assert dg.read_drive_state("/dev/sdb", run=runner(f"sdb disk  {GUID} \n")).has_data is False


@pytest.mark.parametrize("output", [
    DATA, f"sdb disk  {GUID} \nsdb1 part  \n",                       # a partition, even with no recognised filesystem
    f"sdb disk ext4 {GUID} \n",                                       # a filesystem straight on the disk
    f"sdb disk LVM2_member {GUID} \nvg-root lvm ext4 \n", f"sdb disk  {GUID} \nsdb1 part crypto_LUKS  \n",
    f"sdb disk  {GUID} \nmd0 raid1  \n", f"sdb disk linux_raid_member {GUID} \n",
])
def test_partitions_filesystems_lvm_and_encryption_all_count_as_data(output):
    assert dg.read_drive_state("/dev/sdb", run=runner(output)).has_data is True


@pytest.mark.parametrize("output,rc", [("", 0), ("garbage\n", 0), ("sdb\n", 0), (BLANK, 1), ("lsblk: not a block device\n", 32)])
def test_an_unreadable_or_unparseable_state_is_treated_as_having_data(output, rc):
    state = dg.read_drive_state("/dev/sdb", run=runner(output, rc))
    assert state.known is False and state.has_data is True


def test_the_runner_only_reads(monkeypatch):
    run = runner(BLANK)
    dg.read_drive_state("/dev/sdb", run=run)
    assert run.calls and run.calls[0][0] == "lsblk"
    assert all(c[0] == "lsblk" for c in run.calls)


# --- the rule ------------------------------------------------------------------------

def test_an_empty_drive_may_be_formatted_without_any_uuid():
    assert dg.require_may_format("/dev/sdb", run=runner(BLANK)) is None


def test_a_drive_with_data_and_no_installer_uuid_is_refused_with_no_override():
    with pytest.raises(dg.DataProtectionError, match="installer"):
        dg.require_may_format("/dev/sdb", run=runner(DATA))


def test_a_drive_with_data_and_an_installer_uuid_may_be_formatted():
    dg.register_installer_uuid(GUID, serial="SYNTHDRIVEB00002")
    assert dg.require_may_format("/dev/sdb", run=runner(DATA)) is None


def test_the_uuid_match_ignores_case():
    dg.register_installer_uuid(GUID.upper(), serial="X")
    assert dg.require_may_format("/dev/sdb", run=runner(DATA)) is None
    assert dg.require_may_format("/dev/sdb", run=runner(DATA.replace(GUID, GUID.upper()))) is None


def test_a_different_drives_uuid_does_not_unlock_this_one():
    dg.register_installer_uuid("11111111-2222-3333-4444-555555555555", serial="OTHER")
    with pytest.raises(dg.DataProtectionError):
        dg.require_may_format("/dev/sdb", run=runner(DATA))


def test_a_drive_with_data_and_no_guid_at_all_is_refused():
    dg.register_installer_uuid(GUID, serial="X")
    with pytest.raises(dg.DataProtectionError):
        dg.require_may_format("/dev/sdb", run=runner("sdb disk  \nsdb1 part ntfs  TV\n"))


def test_an_unreadable_drive_is_refused_even_though_it_might_be_empty():
    with pytest.raises(dg.DataProtectionError):
        dg.require_may_format("/dev/sdb", run=runner("", 1))


def test_there_is_no_parameter_that_overrides_the_rule():
    params = set(inspect.signature(dg.require_may_format).parameters)
    assert params == {"device_path", "run", "serial"}
    for forbidden in ("force", "override", "confirmed", "bypass", "allow", "yes", "skip"):
        assert forbidden not in params


def test_registering_a_uuid_needs_a_plain_guid():
    for bad in ("", "not-a-guid", "../etc", "x" * 100, None):
        with pytest.raises(ValueError):
            dg.register_installer_uuid(bad, serial="X")


def test_the_installer_generates_a_fresh_uuid_each_time():
    ids = {dg.new_installer_uuid() for _ in range(20)}
    assert len(ids) == 20 and all(len(i) == 36 for i in ids)


# --- adopting an existing Baseline drive (non-destructive) -------------------------------

class Cmd:
    """A privileged runner that records argv and 'applies' sgdisk -U to the fake drive's GUID."""

    def __init__(self, output=BASELINE_DRIVE):
        self.output, self.calls = output, []

    def run(self, argv, timeout=60):
        self.calls.append(list(argv))
        if argv[:2] == ["sgdisk", "-U"]:
            self.output = self.output.replace(GUID, argv[2])
        import types
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    def reader(self, argv):
        if "SERIAL" in argv:
            return 0, "UNLOCKED-TEST-DISK\n"
        return 0, self.output


def test_a_baseline_drive_can_be_stamped_and_is_then_recognised():
    cmd = Cmd()
    result = dg.stamp_installer_identity(cmd, "/dev/sdb", serial="SYNTHDRIVEB00002", read=cmd.reader)
    assert result.ok is True
    assert [c for c in cmd.calls if c[0] == "sgdisk"][0][:2] == ["sgdisk", "-U"]
    assert dg.require_may_format("/dev/sdb", run=cmd.reader) is None                  # now protected-but-formattable by the installer
    assert dg.read_drive_state("/dev/sdb", run=cmd.reader).ptuuid != GUID


def test_stamping_changes_only_the_disk_guid():
    cmd = Cmd()
    dg.stamp_installer_identity(cmd, "/dev/sdb", serial="X", read=cmd.reader)
    assert all(c[:2] == ["sgdisk", "-U"] for c in cmd.calls)


def test_a_blank_drive_can_be_stamped():
    cmd = Cmd(BLANK)
    assert dg.stamp_installer_identity(cmd, "/dev/sdb", serial="X", read=cmd.reader).ok is True


@pytest.mark.parametrize("output", [DATA, f"sdb disk  {GUID} \nsdb1 part ext4  photos\n",
                                    f"sdb disk  {GUID} \nsdb1 part ext4  BASELINE\nsdb2 part ntfs  TV\n", ""])
def test_a_drive_that_is_not_baselines_own_cannot_be_adopted_so_stamping_is_no_back_door(output):
    cmd = Cmd(output)
    result = dg.stamp_installer_identity(cmd, "/dev/sdb", serial="X", read=cmd.reader)
    assert result.ok is False and cmd.calls == []
    with pytest.raises(dg.DataProtectionError):
        dg.require_may_format("/dev/sdb", run=cmd.reader)


def test_a_stamp_that_does_not_stick_is_not_registered():
    class Stubborn(Cmd):
        def run(self, argv, timeout=60):
            self.calls.append(list(argv))
            import types
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")      # claims success, changes nothing
    cmd = Stubborn()
    result = dg.stamp_installer_identity(cmd, "/dev/sdb", serial="X", read=cmd.reader)
    assert result.ok is False
    assert dg.is_installer_uuid(GUID) is False


def test_a_failing_sgdisk_is_reported_and_nothing_is_registered():
    class Failing(Cmd):
        def run(self, argv, timeout=60):
            self.calls.append(list(argv))
            import types
            return types.SimpleNamespace(returncode=2, stdout="", stderr="no permission")
    cmd = Failing()
    assert dg.stamp_installer_identity(cmd, "/dev/sdb", serial="X", read=cmd.reader).ok is False
    assert registry.list_entries(dg.REGISTRY_TYPE, scope=registry.GLOBAL) == {}


# --- the development-phase lock (operator, 2026-10-11) --------------------------------------------------------
# The 2026-10-01 rule exists because drive selection was uncontrolled and a drive full of real data was nearly
# formatted. While this effort is locked to ONE named development drive, that risk does not exist for that drive; for
# every other drive, and for every drive once the lock is removed, the rule is the same hard requirement as before.

PC601 = "SYNTHDRIVEA00001"
PC401 = "SYNTHDRIVEB00002"


def runner_with_serial(listing, serial, serial_rc=0):
    def run(argv):
        if "SERIAL" in argv:
            return serial_rc, serial
        return 0, listing
    return run


def test_the_lock_comes_from_the_operators_own_data_file_and_covers_only_what_that_file_marks_disposable(tmp_path):
    f = tmp_path / "own-drives"
    f.write_text("# this lane's drives\nSYNTHDRIVEA00001 disposable\nSYNTHDRIVEB00002\nbad serial here\nSYNTHDRIVEC00003 something-else\n")
    lane = "4af8c95a-1c9b-437a-a306-c53855d4077f"
    assert dg.own_drive_serials(f, lane) == frozenset({PC601, PC401})                                   # allowed targets: every well-formed line
    assert dg.own_drive_serials(f, lane, disposable_only=True) == frozenset({PC601})                    # the lock: only what the operator marked
    assert dg.own_drive_serials(f, None) == frozenset() and dg.own_drive_serials(tmp_path / "absent", lane) == frozenset()   # no lane identity, or no file: nothing
    assert dg.record_own_drive("SYNTHDRIVEC00003", f) is True and dg.record_own_drive("SYNTHDRIVEC00003", f) is False
    assert "SYNTHDRIVEC00003" in dg.own_drive_serials(f, lane) and "SYNTHDRIVEC00003" not in dg.own_drive_serials(f, lane, disposable_only=True)
    with pytest.raises(ValueError):
        dg.record_own_drive("bad serial; rm", f)


def test_no_serial_is_stored_in_the_guards_source():
    import re
    from pathlib import Path
    source = Path(dg.__file__).read_text()
    assert not re.search(r"['\"][A-Z0-9]{12,}['\"]", source)                                         # a long bare serial-looking literal would be a stored serial


LANE_TARGET = PC601
PROTECTED_TARGET = PC401


def test_the_locked_development_drive_may_be_formatted_even_though_it_holds_foreign_data():
    assert dg.require_may_format("/dev/sdb", run=runner_with_serial(DATA, LANE_TARGET + "\n")) is None


OTHER_LANE = "11111111-2222-4333-8444-555555555555"            # a lane that is not this one (a lane identifier, not a drive)


def listing_with_stamp(stamp):
    return f"sdb disk  {stamp} \n"                               # no partitions at all: an empty-looking disk, but carrying a stamp


def test_a_drive_stamped_by_another_lane_stays_protected_even_if_lsblk_reports_it_as_empty():
    """Protection comes from the identifier on the drive itself (the lane that installed it, proved by the drive's own serial inside the identifier), not from a list of serials."""
    import identifiers
    stamp = identifiers.host_id(OTHER_LANE, PROTECTED_TARGET)
    with pytest.raises(dg.DataProtectionError, match="another installer lane"):
        dg.require_may_format("/dev/sdb", run=runner_with_serial(listing_with_stamp(stamp), PROTECTED_TARGET + "\n"))
    assert dg.lane_verdict(stamp, PROTECTED_TARGET) == "other"
    assert dg.lane_verdict(stamp, "SOMEOTHERSERIAL01") == "none"                     # the same identifier on a drive with a different serial proves nothing
    assert dg.lane_verdict(identifiers.host_id("4af8c95a-1c9b-437a-a306-c53855d4077f", LANE_TARGET), LANE_TARGET) == "ours"
    assert dg.lane_verdict(None, PROTECTED_TARGET) == "none" and dg.lane_verdict("not-a-guid", PROTECTED_TARGET) == "none"


def test_another_lanes_stamp_is_refused_even_for_a_drive_the_operator_listed_as_disposable(monkeypatch):
    import identifiers
    from conftest import set_own_drives
    set_own_drives(monkeypatch, [])
    stamp = identifiers.host_id(OTHER_LANE, LANE_TARGET)
    with pytest.raises(dg.DataProtectionError, match="another installer lane"):
        dg.require_may_format("/dev/sdb", run=runner_with_serial(listing_with_stamp(stamp), LANE_TARGET + "\n"))


@pytest.mark.parametrize("serial", [PROTECTED_TARGET, "SOMEONE-ELSES-TERABYTES", "SYNTHDRIVEA0000", LANE_TARGET.lower(), ""])
def test_every_other_drive_holding_data_is_still_refused(serial):
    with pytest.raises(dg.DataProtectionError, match="no override"):
        dg.require_may_format("/dev/sdb", run=runner_with_serial(DATA, serial + "\n"))


@pytest.mark.parametrize("serial,rc", [("", 1), (LANE_TARGET + "\n" + PROTECTED_TARGET + "\n", 0), (LANE_TARGET + " " + PROTECTED_TARGET, 0)])
def test_a_serial_that_cannot_be_read_or_is_ambiguous_does_not_unlock_anything(serial, rc):
    with pytest.raises(dg.DataProtectionError):
        dg.require_may_format("/dev/sdb", run=runner_with_serial(DATA, serial, rc))


def test_a_prevalidated_exact_serial_can_be_passed_without_a_second_serial_probe():
    calls = []
    def run(argv):
        calls.append(list(argv))
        if "SERIAL" in argv:
            raise AssertionError("guard must use the exact serial returned by device validation")
        return 0, DATA
    assert dg.require_may_format("/dev/sdb", run=run, serial=LANE_TARGET) is None
    assert not any("SERIAL" in call for call in calls)


def test_the_lock_never_applies_to_a_drive_whose_contents_cannot_be_read():
    def run(argv):
        return (0, LANE_TARGET + "\n") if "SERIAL" in argv else (1, "")
    with pytest.raises(dg.DataProtectionError):
        dg.require_may_format("/dev/sdb", run=run)


def test_removing_the_lock_restores_the_hard_requirement_for_that_drive_too(monkeypatch):
    from conftest import set_own_drives
    set_own_drives(monkeypatch, [])
    with pytest.raises(dg.DataProtectionError, match="no override"):
        dg.require_may_format("/dev/sdb", run=runner_with_serial(DATA, LANE_TARGET + "\n"))


def test_the_lock_is_a_module_constant_never_a_parameter():
    assert set(inspect.signature(dg.require_may_format).parameters) == {"device_path", "run", "serial"}


def test_a_failed_serial_probe_cannot_fall_through_to_a_registered_installer_guid():
    state = dg.DriveState(known=True, has_data=True, ptuuid=GUID)
    with pytest.raises(dg.DataProtectionError, match="serial"):
        dg._authorize_format("/dev/sdb", state, serial=None, installer_uuid_registered=True)


def test_an_unknown_or_partition_target_cannot_use_a_registered_installer_guid():
    state = dg.DriveState(known=False, has_data=True, ptuuid=GUID)
    with pytest.raises(dg.DataProtectionError, match="serial|read"):
        dg._authorize_format("/dev/sdb1", state, serial=None, installer_uuid_registered=True)
