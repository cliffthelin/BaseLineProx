"""Each installer has its own UUID; the identity of a drive it installed is derived from that UUID and the drive's serial, so it
never changes across reinstalls, differs between installers, and is stamped on the drive and registered against the serial.

Real files and real uuid arithmetic; the only injected pieces are the two device calls (sgdisk and the GUID probe)."""
import uuid

import pytest

import drive_guard
import installer_identity as ii

PC601 = "FD01N6557110C271B"
PC401 = "MD89N41071210AP4E"


def test_an_installer_gets_one_identity_and_keeps_it(tmp_path):
    first = ii.installer_id(tmp_path)
    assert str(uuid.UUID(first)) == first
    assert ii.installer_id(tmp_path) == first
    assert (tmp_path / ii.FILE_NAME).read_text().strip() == first


def test_two_installers_never_share_an_identity(tmp_path):
    (tmp_path / "claude").mkdir()
    (tmp_path / "codex").mkdir()
    assert ii.installer_id(tmp_path / "claude") != ii.installer_id(tmp_path / "codex")


def test_a_damaged_identity_file_is_refused_not_silently_replaced(tmp_path):
    """An identity that changes silently is exactly what this exists to prevent."""
    (tmp_path / ii.FILE_NAME).write_text("not a uuid\n")
    with pytest.raises(ii.IdentityError):
        ii.installer_id(tmp_path)
    assert (tmp_path / ii.FILE_NAME).read_text() == "not a uuid\n"


def test_a_drives_identity_is_fixed_by_installer_and_serial_alone():
    installer = str(uuid.uuid4())
    assert ii.child_uuid(installer, PC601) == ii.child_uuid(installer, PC601)
    assert ii.child_uuid(installer, PC601) != ii.child_uuid(installer, PC401)           # aligned to the serial
    assert ii.child_uuid(installer, PC601) != ii.child_uuid(str(uuid.uuid4()), PC601)   # and to the installer
    assert drive_guard.normalize_guid(ii.child_uuid(installer, PC601)) == ii.child_uuid(installer, PC601)


@pytest.mark.parametrize("serial", ["", "bad serial!", "x" * 65])
def test_a_serial_that_is_not_a_plain_serial_has_no_identity(serial):
    with pytest.raises(ii.IdentityError):
        ii.child_uuid(str(uuid.uuid4()), serial)


def _device(initial):
    state = {"guid": initial, "calls": []}

    def run(argv):
        state["calls"].append(list(argv))
        if argv[0] == "sgdisk" and argv[1] == "-U":
            state["guid"] = argv[2]
        return 0, ""

    def probe(device):
        return state["guid"]
    return state, run, probe


def test_stamping_sets_the_drives_disk_identifier_and_registers_it_against_the_serial():
    installer = str(uuid.uuid4())
    wanted = ii.child_uuid(installer, PC601)
    state, run, probe = _device("0b9adfbf-7213-4792-81e6-9fe668b01c57")           # what Proxmox's installer generated
    assert ii.stamp_child_identity("/dev/sdb", PC601, installer, run=run, probe=probe) == wanted
    assert state["calls"] == [["sgdisk", "-U", wanted, "/dev/sdb"]]
    assert drive_guard.is_installer_uuid(wanted)


def test_stamping_again_changes_nothing_and_registers_no_second_entry():
    installer = str(uuid.uuid4())
    wanted = ii.child_uuid(installer, PC601)
    state, run, probe = _device(wanted)
    assert ii.stamp_child_identity("/dev/sdb", PC601, installer, run=run, probe=probe) == wanted
    assert state["calls"] == []                                                   # already carries it: nothing written
    import registry
    entries = registry.list_entries(drive_guard.REGISTRY_TYPE, scope=registry.GLOBAL, read_only=True)
    assert list(entries).count(wanted) == 1


def test_a_stamp_that_does_not_stick_is_never_registered():
    installer = str(uuid.uuid4())
    wanted = ii.child_uuid(installer, PC601)
    state = {"guid": "11111111-2222-4333-8444-555555555555"}
    with pytest.raises(ii.IdentityError, match="did not take"):
        ii.stamp_child_identity("/dev/sdb", PC601, installer, run=lambda argv: (0, ""),
                                probe=lambda device: state["guid"])
    assert not drive_guard.is_installer_uuid(wanted)


def test_a_failing_sgdisk_is_reported_and_nothing_is_registered():
    installer = str(uuid.uuid4())
    with pytest.raises(ii.IdentityError, match="sgdisk"):
        ii.stamp_child_identity("/dev/sdb", PC601, installer, run=lambda argv: (1, "cannot write"),
                                probe=lambda device: "11111111-2222-4333-8444-555555555555")
    assert not drive_guard.is_installer_uuid(ii.child_uuid(installer, PC601))


# --- the lane's own pinned installer UUID (baseline/INSTALLER_UUID) -----------------------------------------------

CODEX_LANE_UUID = "5029a80d-c748-4616-aa08-99ac560f5311"           # the parallel lane's value: never copied into this one
CLAUDE_LANE_UUID = "4af8c95a-1c9b-437a-a306-c53855d4077f"          # this lane's value; every drive it installed derives from it


def test_this_lanes_pinned_installer_uuid_is_its_own_and_never_the_parallel_lanes():
    from pathlib import Path
    pinned = (Path(__file__).resolve().parents[2] / "baseline" / ii.FILE_NAME).read_text().strip()
    assert str(uuid.UUID(pinned)) == pinned
    assert pinned == CLAUDE_LANE_UUID                              # changing it changes every drive's identity: a conscious edit
    assert pinned != CODEX_LANE_UUID


def test_the_same_serial_gets_a_different_identity_in_each_lane():
    assert ii.child_uuid(CLAUDE_LANE_UUID, PC601) != ii.child_uuid(CODEX_LANE_UUID, PC601)


def test_a_merge_keeps_the_receiving_lanes_own_uuid_file():
    from pathlib import Path
    attributes = (Path(__file__).resolve().parents[2] / ".gitattributes").read_text().splitlines()
    assert any(line.split()[:2] == ["baseline/INSTALLER_UUID", "merge=ours"] for line in attributes)
