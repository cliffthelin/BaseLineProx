"""No formatting a drive that holds data unless the Baseline installer made it (operator instruction 2026-10-01).

A drive "has data" if it has any partition, filesystem, LVM or encrypted volume; a blank drive, or one with an
empty partition table, has none; a drive whose state cannot be read is treated as having data. A drive counts
as installer-made only if its GPT disk GUID is one the installer generated and registered. There is no override:
no parameter, human confirmation or standing approval can format a drive with data and no installer UUID.
Everything here uses fake runners; nothing opens a device."""
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
    dg.register_installer_uuid(GUID, serial="MD89N41071210AP4E")
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
    assert params == {"device_path", "run"}
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
        return 0, self.output


def test_a_baseline_drive_can_be_stamped_and_is_then_recognised():
    cmd = Cmd()
    result = dg.stamp_installer_identity(cmd, "/dev/sdb", serial="MD89N41071210AP4E", read=cmd.reader)
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
