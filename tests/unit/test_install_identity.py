"""Unit tests for install_identity.py - a per-install UUID that survives
rebuilds and is never silently shared by clones."""
import json
import uuid

import pytest
from fake_runner import FakeRunner

import install_identity as ii

UUID_A = "11111111-1111-4111-8111-111111111111"
UUID_B = "22222222-2222-4222-8222-222222222222"
UUID_C = "33333333-3333-4333-8333-333333333333"


def _uuids(*values):
    it = iter(values)
    return lambda: uuid.UUID(next(it))


def _hw(product_uuid="4c4c4544-0042-3510-8054-b3c04f383732", board="BOARD-SN-0001",
        product="SYS-SN-0001"):
    return FakeRunner(files={
        "/sys/class/dmi/id/product_uuid": product_uuid + "\n",
        "/sys/class/dmi/id/board_serial": board + "\n",
        "/sys/class/dmi/id/product_serial": product + "\n",
    })


# -- Fingerprint -------------------------------------------------------

def test_fingerprint_is_stable_for_the_same_hardware():
    assert ii.hardware_fingerprint(_hw()).digest == ii.hardware_fingerprint(_hw()).digest


def test_fingerprint_differs_between_two_otherwise_identical_machines():
    """Thirty identical machines share model names; only serials and the
    SMBIOS UUID tell them apart."""
    a = ii.hardware_fingerprint(_hw(board="SN-A", product="P-A", product_uuid=UUID_A))
    b = ii.hardware_fingerprint(_hw(board="SN-B", product="P-B", product_uuid=UUID_B))
    assert a.digest != b.digest


def test_model_names_are_never_fingerprint_sources():
    for path in ii._FINGERPRINT_SOURCES:
        assert "product_name" not in path and "vendor" not in path


@pytest.mark.parametrize("placeholder", [
    "03000200-0400-0500-0006-000700080009",
    "00000000-0000-0000-0000-000000000000",
    "To Be Filled By O.E.M.",
    "Default string",
])
def test_a_placeholder_smbios_value_is_flagged_as_weak(placeholder):
    """Vendors ship these identically on every unit of a model; a fleet of
    such boards would otherwise all fingerprint the same."""
    fp = ii.hardware_fingerprint(_hw(product_uuid=placeholder))
    assert fp.weak is True
    assert "/sys/class/dmi/id/product_uuid" in fp.placeholders


def test_unreadable_sources_are_reported_not_fatal():
    """Unprivileged, the SMBIOS fields are mode 0400."""
    fp = ii.hardware_fingerprint(FakeRunner())
    assert fp.available is False
    assert len(fp.unreadable) == len(ii._FINGERPRINT_SOURCES)


# -- Minting -----------------------------------------------------------

def test_first_boot_mints_an_origin_identity():
    runner = _hw()
    ident, status = ii.ensure_identity(runner, now=1.0, fingerprint=ii.hardware_fingerprint(runner),
                                       new_uuid=_uuids(UUID_A))
    assert status == ii.STATUS_CREATED
    assert ident.install_id == UUID_A
    assert ident.parent_id is None and ident.generation == 0


def test_the_identity_lives_on_the_substrate_volume():
    """SUBSTRATE survives a substrate rebuild; /etc/machine-id does not."""
    assert ii.DEFAULT_PATH.startswith("/mnt/SUBSTRATE/")


def test_an_existing_identity_is_never_overwritten():
    runner = _hw()
    fp = ii.hardware_fingerprint(runner)
    first, _ = ii.ensure_identity(runner, now=1.0, fingerprint=fp, new_uuid=_uuids(UUID_A))
    again, status = ii.ensure_identity(runner, now=2.0, fingerprint=fp, new_uuid=_uuids(UUID_B))
    assert status == ii.STATUS_EXISTING
    assert again.install_id == first.install_id == UUID_A


def test_a_replica_records_its_parent_and_generation():
    """Replication mints a fresh id and keeps the lineage, so a fleet is a
    family tree rather than a set of duplicates."""
    runner = _hw()
    ident, _ = ii.ensure_identity(runner, now=1.0, fingerprint=ii.hardware_fingerprint(runner),
                                  parent_id=UUID_A, parent_generation=0, new_uuid=_uuids(UUID_B))
    assert ident.install_id == UUID_B
    assert ident.parent_id == UUID_A
    assert ident.generation == 1


def test_replication_never_carries_the_identity():
    assert ii.DEFAULT_PATH in ii.REPLICATION_EXCLUDES
    assert ii.DEFAULT_PATH + ii.HISTORY_PATH_SUFFIX in ii.REPLICATION_EXCLUDES


# -- Clone detection ---------------------------------------------------

def _cloned_onto_new_hardware():
    origin = _hw(product_uuid=UUID_A, board="SN-A", product="P-A")
    ii.ensure_identity(origin, now=1.0, fingerprint=ii.hardware_fingerprint(origin),
                       new_uuid=_uuids(UUID_A))
    clone = _hw(product_uuid=UUID_B, board="SN-B", product="P-B")
    for path in (ii.DEFAULT_PATH, ii.DEFAULT_PATH + ii.HISTORY_PATH_SUFFIX):
        clone.files[path] = origin.files[path]                     # the whole disk was copied
    return clone


def test_a_copied_identity_on_different_hardware_is_detected_not_believed():
    clone = _cloned_onto_new_hardware()
    ident, status = ii.ensure_identity(clone, now=2.0, fingerprint=ii.hardware_fingerprint(clone),
                                       new_uuid=_uuids(UUID_C))
    assert status == ii.STATUS_HARDWARE_CHANGED
    assert ident.install_id == UUID_A


def test_detecting_a_hardware_change_changes_nothing():
    """Moved disk or clone cannot be told from the disk - never guessed."""
    clone = _cloned_onto_new_hardware()
    before = clone.files[ii.DEFAULT_PATH]
    ii.ensure_identity(clone, now=2.0, fingerprint=ii.hardware_fingerprint(clone),
                       new_uuid=_uuids(UUID_C))
    assert clone.files[ii.DEFAULT_PATH] == before


def test_fork_turns_a_clone_into_a_new_install_with_its_origin_as_parent():
    clone = _cloned_onto_new_hardware()
    forked = ii.fork_identity(clone, now=3.0, fingerprint=ii.hardware_fingerprint(clone),
                              new_uuid=_uuids(UUID_C))
    assert forked.install_id == UUID_C
    assert forked.parent_id == UUID_A
    assert forked.generation == 1
    assert ii.ensure_identity(clone, now=4.0, fingerprint=ii.hardware_fingerprint(clone))[1] == ii.STATUS_EXISTING


def test_adopt_keeps_the_id_when_a_disk_was_moved():
    clone = _cloned_onto_new_hardware()
    moved = ii.adopt_hardware(clone, now=3.0, fingerprint=ii.hardware_fingerprint(clone))
    assert moved.install_id == UUID_A
    assert ii.ensure_identity(clone, now=4.0, fingerprint=ii.hardware_fingerprint(clone))[1] == ii.STATUS_EXISTING


def test_every_change_is_appended_to_the_history():
    clone = _cloned_onto_new_hardware()
    ii.fork_identity(clone, now=3.0, fingerprint=ii.hardware_fingerprint(clone),
                     new_uuid=_uuids(UUID_C))
    events = [json.loads(line)["event"]
              for line in clone.files[ii.DEFAULT_PATH + ii.HISTORY_PATH_SUFFIX].splitlines()]
    assert events == ["created", "forked"]


def test_without_a_readable_fingerprint_status_says_so():
    runner = FakeRunner()
    ii.ensure_identity(runner, now=1.0, fingerprint=ii.hardware_fingerprint(runner),
                       new_uuid=_uuids(UUID_A))
    _, status = ii.ensure_identity(runner, now=2.0, fingerprint=ii.hardware_fingerprint(runner))
    assert status == ii.STATUS_FINGERPRINT_UNAVAILABLE


# -- Alias -------------------------------------------------------------

def test_an_alias_is_a_soft_name_that_never_changes_the_id():
    runner = _hw()
    ii.ensure_identity(runner, now=1.0, fingerprint=ii.hardware_fingerprint(runner),
                       new_uuid=_uuids(UUID_A))
    named = ii.set_alias(runner, "lab-03", now=2.0)
    assert named.alias == "lab-03" and named.install_id == UUID_A


def test_an_unsafe_alias_is_refused():
    runner = _hw()
    ii.ensure_identity(runner, now=1.0, fingerprint=ii.hardware_fingerprint(runner),
                       new_uuid=_uuids(UUID_A))
    with pytest.raises(Exception):
        ii.set_alias(runner, "../etc", now=2.0)


def test_a_corrupt_stored_id_is_refused():
    runner = FakeRunner(files={ii.DEFAULT_PATH: json.dumps({"install_id": "not-a-uuid", "created_at": 1})})
    with pytest.raises(ii.IdentityError):
        ii.read_identity(runner)
