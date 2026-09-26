"""Tests for physical_device_safety.py - the real-block-device analog of
tools/qemu_harness_safety.py's validate_image_path. Uses a FakeRunner
(this project's established Runner/FakeRunner pattern, e.g. repair.py)
and synthetic serial numbers only - no real device is ever touched by
these tests, and no real hardware serial number appears in this file
(the actual allowlist for this project's real drives lives in a local,
gitignored config, never in tracked test/source code)."""
import os

import pytest

import physical_device_safety as pds

TEST_TARGET_SERIAL = "TestDriveSerial-001"
TEST_PERSISTENCE_SERIAL = "TestDriveSerial-002"
TEST_BOOT_SERIAL = "TestBootSerial-999"


class FakeRunner:
    """argv -> canned stdout, matched by exact tuple; size lookups and
    lstat/realpath are separately injectable. Raises AssertionError on
    an unexpected call, so a test can't accidentally pass by coincidence."""

    def __init__(self, *, udevadm_by_path=None, findmnt_root="/dev/nvme0n1p2",
                 pkname_of_root="nvme0n1", sizes=None, lstat_mode=None,
                 realpath_map=None, is_symlink=False):
        self.udevadm_by_path = udevadm_by_path or {}
        self.findmnt_root = findmnt_root
        self.pkname_of_root = pkname_of_root
        self.sizes = sizes or {}
        self.lstat_mode = lstat_mode if lstat_mode is not None else 0o60000  # S_IFBLK
        self.realpath_map = realpath_map or {}
        self.is_symlink = is_symlink

    def run(self, argv):
        if argv[0] == "udevadm":
            name_arg = next(a for a in argv if a.startswith("--name="))
            path = name_arg.split("=", 1)[1]
            serial = self.udevadm_by_path.get(path)
            if serial is None:
                return ""
            return f"ID_SERIAL_SHORT={serial}\n"
        if argv[0] == "findmnt":
            return self.findmnt_root + "\n"
        if argv[0] == "lsblk":
            return self.pkname_of_root + "\n"
        raise AssertionError(f"unexpected command: {argv}")

    def lstat(self, path):
        class _Stat:
            def __init__(self, mode):
                self.st_mode = mode
        return _Stat(self.lstat_mode)

    def realpath(self, path):
        return self.realpath_map.get(path, path)

    def read_size_file(self, dev_name):
        return str(self.sizes.get(dev_name, 0))


GOOD_SIZE_SECTORS = 1_000_215_216  # matches a ~512GB drive, in 512-byte sectors


def _good_runner(**overrides):
    defaults = dict(
        udevadm_by_path={
            "/dev/sdd": TEST_TARGET_SERIAL,
            "/dev/sdb": TEST_PERSISTENCE_SERIAL,
            "/dev/nvme0n1": TEST_BOOT_SERIAL,
        },
        sizes={"sdd": GOOD_SIZE_SECTORS, "sdb": GOOD_SIZE_SECTORS},
    )
    defaults.update(overrides)
    return FakeRunner(**defaults)


def _validate_sdd(runner):
    return pds.validate_target_device(
        "/dev/sdd", expected_serial=TEST_TARGET_SERIAL,
        min_size_bytes=500_000_000_000, max_size_bytes=520_000_000_000, runner=runner)


def test_valid_target_passes_and_returns_expected_dict():
    result = _validate_sdd(_good_runner())
    assert result["path"] == "/dev/sdd"
    assert result["serial"] == TEST_TARGET_SERIAL
    assert result["size_bytes"] == GOOD_SIZE_SECTORS * 512


def test_wrong_serial_is_refused():
    runner = _good_runner(udevadm_by_path={"/dev/sdd": "SOME-OTHER-SERIAL",
                                            "/dev/nvme0n1": TEST_BOOT_SERIAL})
    with pytest.raises(pds.PhysicalDeviceSafetyError):
        _validate_sdd(runner)


def test_no_serial_reported_is_refused():
    runner = _good_runner(udevadm_by_path={"/dev/nvme0n1": TEST_BOOT_SERIAL})  # sdd absent
    with pytest.raises(pds.PhysicalDeviceSafetyError):
        _validate_sdd(runner)


def test_boot_device_serial_is_refused_even_if_explicitly_targeted():
    """The decisive safety property: even if a caller passes the boot
    device's own path and somehow expects its serial to match, the
    self-detected boot-device check refuses it independently."""
    runner = _good_runner(
        udevadm_by_path={"/dev/sdd": TEST_BOOT_SERIAL, "/dev/nvme0n1": TEST_BOOT_SERIAL})
    with pytest.raises(pds.PhysicalDeviceSafetyError):
        pds.validate_target_device(
            "/dev/sdd", expected_serial=TEST_BOOT_SERIAL,
            min_size_bytes=0, max_size_bytes=10**15, runner=runner)


def test_size_out_of_range_is_refused():
    runner = _good_runner(sizes={"sdd": 100})  # far too small
    with pytest.raises(pds.PhysicalDeviceSafetyError):
        _validate_sdd(runner)


def test_size_slightly_above_range_is_refused():
    runner = _good_runner(sizes={"sdd": 2_000_000_000})  # ~1TB in sectors, too big for range
    with pytest.raises(pds.PhysicalDeviceSafetyError):
        _validate_sdd(runner)


def test_non_block_device_is_refused():
    runner = _good_runner(lstat_mode=0o100000)  # S_IFREG - a regular file, not a block device
    with pytest.raises(pds.PhysicalDeviceSafetyError):
        _validate_sdd(runner)


def test_symlink_is_refused_before_any_other_check(monkeypatch):
    monkeypatch.setattr(os.path, "islink", lambda p: True)
    with pytest.raises(pds.PhysicalDeviceSafetyError):
        _validate_sdd(_good_runner())


def test_symlink_resolving_to_the_correct_device_is_still_refused(monkeypatch):
    """A symlink must be refused on its own, even if it happens to
    resolve to an otherwise-valid target - mirrors qemu_harness_safety's
    "checked on the literal given path, before realpath() would follow
    it" discipline."""
    monkeypatch.setattr(os.path, "islink", lambda p: p == "/dev/sdd-link")
    with pytest.raises(pds.PhysicalDeviceSafetyError):
        pds.validate_target_device(
            "/dev/sdd-link", expected_serial=TEST_TARGET_SERIAL,
            min_size_bytes=500_000_000_000, max_size_bytes=520_000_000_000,
            runner=_good_runner(realpath_map={"/dev/sdd-link": "/dev/sdd"}))


# --- caller-supplied allowlist ----------------------------------------------

TEST_TARGETS = {
    "sdd-blank-substrate": {
        "expected_serial": TEST_TARGET_SERIAL,
        "min_size_bytes": 500_000_000_000,
        "max_size_bytes": 520_000_000_000,
    },
    "sdb-persistence": {
        "expected_serial": TEST_PERSISTENCE_SERIAL,
        "min_size_bytes": 500_000_000_000,
        "max_size_bytes": 520_000_000_000,
    },
}


def test_validate_known_target_sdd():
    runner = _good_runner()
    result = pds.validate_known_target("/dev/sdd", "sdd-blank-substrate", TEST_TARGETS,
                                        runner=runner)
    assert result["serial"] == TEST_TARGET_SERIAL


def test_validate_known_target_sdb():
    runner = _good_runner()
    result = pds.validate_known_target("/dev/sdb", "sdb-persistence", TEST_TARGETS,
                                        runner=runner)
    assert result["serial"] == TEST_PERSISTENCE_SERIAL


def test_validate_known_target_rejects_unknown_name():
    with pytest.raises(pds.PhysicalDeviceSafetyError):
        pds.validate_known_target("/dev/sdd", "some-other-drive", TEST_TARGETS,
                                   runner=_good_runner())


# --- destructive helper only accepts the validated dict, never a path -----

def test_wipe_signatures_only_accepts_the_validated_dict():
    runner = _good_runner()
    validated = _validate_sdd(runner)
    calls = []
    runner.run = lambda argv: calls.append(argv) or ""
    pds.wipe_signatures(validated, runner=runner)
    assert calls == [["wipefs", "-a", "/dev/sdd"]]


def test_load_carrier_identities_from_persistence_manifest_adapts_the_shape():
    """The manifest is the intended source of truth for `targets` in
    practice - identifiers live in persistence data, not a repo-local
    config file. This proves the adapter reshapes a manifest's own
    recorded carrier-identity section correctly."""
    manifest = {
        "carrier_identities": {
            "sdd-blank-substrate": {"serial": TEST_TARGET_SERIAL,
                                     "min_size_bytes": 500_000_000_000,
                                     "max_size_bytes": 520_000_000_000},
            "sdb-persistence": {"serial": TEST_PERSISTENCE_SERIAL,
                                 "min_size_bytes": 500_000_000_000,
                                 "max_size_bytes": 520_000_000_000},
        }
    }
    targets = pds.load_carrier_identities_from_persistence_manifest(manifest)
    assert targets == TEST_TARGETS

    result = pds.validate_known_target("/dev/sdd", "sdd-blank-substrate", targets,
                                        runner=_good_runner())
    assert result["serial"] == TEST_TARGET_SERIAL


def test_load_carrier_identities_from_persistence_manifest_handles_absent_section():
    """A manifest that doesn't have this section yet (e.g. before Track
    A2 has ever run) yields an empty targets dict, not an error - the
    caller decides what to do with "no known carriers yet"."""
    assert pds.load_carrier_identities_from_persistence_manifest({}) == {}


def test_wipe_signatures_has_no_bare_path_parameter():
    """Structural proof, not just a convention: wipe_signatures' only
    positional/keyword parameter for the target is `validated`, a dict -
    there is no way to call it with a plain path string."""
    import inspect
    sig = inspect.signature(pds.wipe_signatures)
    params = list(sig.parameters)
    assert params[0] == "validated"
    assert "path" not in params
