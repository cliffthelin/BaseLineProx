"""Deliberate drive enrollment (direct instruction 2026-10-03, extending v0.2 row 55).

Row 55 limits every drive action to the SK hynix drives Baseline is set up with. An installer has to work on the
drives in front of it, so another drive can be added - deliberately: the operator types the drive's serial, it must
match what the drive itself reports, and a person confirms the request like every other drive action. Enrollment
writes nothing to the drive; formatting it is still governed by drive_guard (no data without an installer UUID).
Everything here uses fake runners; nothing opens a device."""
import pytest

import drive_admin as da
import drive_enrollment as de
import physical_device_safety as pds
import registry
from test_drive_admin import FakePdsRunner

NEW = "S6WRNS0TA12638A"
SK_HYNIX = "MD89N41071210AP4E"


# --- the enrollment store ------------------------------------------------------------

def test_nothing_is_enrolled_by_default():
    assert de.enrolled_serials() == frozenset()


def test_an_enrolled_serial_is_remembered_with_what_was_confirmed():
    de.enroll(NEW, size_bytes=1_000_204_886_016, model="Samsung SSD 980 PRO 1TB", now=1_700_000_000.0)
    assert de.enrolled_serials() == frozenset({NEW})
    entry = registry.get_entry(de.REGISTRY_TYPE, NEW, scope=registry.GLOBAL)
    assert entry["attributes"] == {"size_bytes": 1_000_204_886_016, "model": "Samsung SSD 980 PRO 1TB",
                                   "enrolled_at": 1_700_000_000.0}


@pytest.mark.parametrize("serial", ["", "  ", None, "a b", "x" * 41, "../etc", "abc"])
def test_a_missing_or_malformed_serial_is_never_enrolled(serial):
    with pytest.raises(ValueError):
        de.enroll(serial, size_bytes=1, model="m", now=0.0)
    assert de.enrolled_serials() == frozenset()


def test_an_unreadable_store_reads_as_nothing_enrolled(monkeypatch):
    def broken(*a, **k):
        raise OSError("volume not mounted")
    monkeypatch.setattr(registry, "list_entries", broken)
    assert de.enrolled_serials() == frozenset()


# --- drive_admin's gate now admits enrolled drives, and only those ----------------------

def test_the_allowed_set_is_the_sk_hynix_drives_plus_enrolled_ones():
    assert da.allowed_target_serials() == da.ALLOWED_TARGET_SERIALS
    de.enroll(NEW, size_bytes=1, model="m", now=0.0)
    assert da.allowed_target_serials() == da.ALLOWED_TARGET_SERIALS | {NEW}


def test_resolve_target_refuses_a_drive_until_it_is_enrolled():
    with pytest.raises(pds.PhysicalDeviceSafetyError):
        da.resolve_target("/dev/sdc", pds_runner=FakePdsRunner(serial=NEW))
    de.enroll(NEW, size_bytes=1, model="m", now=0.0)
    assert da.resolve_target("/dev/sdc", pds_runner=FakePdsRunner(serial=NEW))["serial"] == NEW


def test_an_enrolled_drive_still_cannot_be_the_boot_device():
    de.enroll(NEW, size_bytes=1, model="m", now=0.0)
    runner = FakePdsRunner(serial=NEW, boot_serial=NEW)
    with pytest.raises(pds.PhysicalDeviceSafetyError):
        da.resolve_target("/dev/sdc", pds_runner=runner)


# --- the enroll_drive action ------------------------------------------------------------

def test_enroll_drive_needs_the_typed_serial_to_match_the_drive():
    with pytest.raises(ValueError, match="refused"):
        da.prepare_action("enroll_drive", {"device_path": "/dev/sdc", "confirm_serial": "WRONGSERIAL1"},
                          pds_runner=FakePdsRunner(serial=NEW))


def test_enroll_drive_needs_a_typed_serial_at_all():
    with pytest.raises(ValueError, match="refused"):
        da.prepare_action("enroll_drive", {"device_path": "/dev/sdc"}, pds_runner=FakePdsRunner(serial=NEW))


def test_a_drive_that_reports_no_serial_cannot_be_enrolled():
    with pytest.raises(ValueError, match="refused"):
        da.prepare_action("enroll_drive", {"device_path": "/dev/sdc", "confirm_serial": "None"},
                          pds_runner=FakePdsRunner(serial=""))


def test_the_boot_device_cannot_be_enrolled():
    with pytest.raises(ValueError, match="refused"):
        da.prepare_action("enroll_drive", {"device_path": "/dev/sdc", "confirm_serial": NEW},
                          pds_runner=FakePdsRunner(serial=NEW, boot_serial=NEW))


def test_a_matching_request_is_prepared_for_human_confirmation_and_enrolls_nothing_yet():
    prepared = da.prepare_action("enroll_drive", {"device_path": "/dev/sdc", "confirm_serial": NEW},
                                 pds_runner=FakePdsRunner(serial=NEW))
    assert prepared["serial"] == NEW
    assert "writes nothing to the drive" in prepared["summary"]
    assert de.enrolled_serials() == frozenset()


def test_enroll_drive_without_a_human_confirmation_runs_nothing():
    result = da.perform_action(None, "enroll_drive", {"device_path": "/dev/sdc", "confirm_serial": NEW},
                               pds_runner=FakePdsRunner(serial=NEW))
    assert result.ok is False and result.detail.startswith("refused")
    assert de.enrolled_serials() == frozenset()


def test_the_enroll_action_records_the_validated_drive_and_touches_no_device():
    pds_runner = FakePdsRunner(serial=NEW, size_bytes=1_000_000_000_000)
    result = da.enroll_drive(None, device_path="/dev/sdc", confirm_serial=NEW, pds_runner=pds_runner,
                             now=1_700_000_000.0)
    assert result.ok, result.detail
    assert de.enrolled_serials() == frozenset({NEW})
    assert pds_runner.wipe_calls == []


def test_enrolling_an_already_allowed_drive_is_a_harmless_no_op():
    result = da.enroll_drive(None, device_path="/dev/sdb", confirm_serial=SK_HYNIX,
                             pds_runner=FakePdsRunner(serial=SK_HYNIX), now=0.0)
    assert result.ok and "already" in result.detail
    assert de.enrolled_serials() == frozenset()


# --- discovery may list other drives, read-only and without detail ------------------------

LSBLK = (
    'NAME="sda" SIZE="4.5T" MODEL="ST5000DM003-2FH18L" TRAN="sata" ROTA="1" SERIAL="WCV00YLT" TYPE="disk"\n'
    'NAME="sdb" SIZE="476.9G" MODEL="PC401 NVMe SK hynix 512GB" TRAN="usb" ROTA="1" SERIAL="MD89N41071210AP4E" TYPE="disk"\n'
    'NAME="nvme0n1" SIZE="953.9G" MODEL="GIGABYTE GP-GSM2NE3100TNTD" TRAN="nvme" ROTA="0" SERIAL="SN211808916391" TYPE="disk"\n'
    'NAME="sdd" SIZE="14.9G" MODEL="Flash" TRAN="usb" ROTA="0" SERIAL="" TYPE="disk"\n'
)


def _runner():
    from fake_runner import FakeProc, FakeRunner
    return FakeRunner(command_responses=[(lambda a: a[0] == "lsblk", FakeProc(0, LSBLK, ""))])


def test_enrollable_drives_are_the_other_non_boot_drives_with_a_serial():
    runner = _runner()
    drives = da.list_enrollable_drives(runner, pds_runner=FakePdsRunner(boot_serial="SN211808916391"))
    assert [(d["path"], d["serial"]) for d in drives] == [("/dev/sda", "WCV00YLT")]
    assert set(drives[0]) == {"path", "serial", "model", "size"}


def test_listing_enrollable_drives_only_reads_the_one_lsblk_listing():
    runner = _runner()
    da.list_enrollable_drives(runner, pds_runner=FakePdsRunner(boot_serial="SN211808916391"))
    assert [c[0] for c in runner.calls] == ["lsblk"]


def test_an_enrolled_drive_moves_to_the_candidate_list():
    de.enroll("WCV00YLT", size_bytes=1, model="m", now=0.0)
    pds_runner = FakePdsRunner(boot_serial="SN211808916391")
    assert da.list_enrollable_drives(_runner(), pds_runner=pds_runner) == []
    assert "/dev/sda" in {d["path"] for d in da.list_candidate_drives(_runner(), pds_runner=pds_runner)}


def test_enrollment_is_confirmed_by_a_person_every_time_and_never_pre_approved():
    import hitl
    assert "enroll_drive" in hitl.CONFIRMED_ACTIONS
    assert "enroll_drive" in hitl.NEVER_PRE_APPROVED
