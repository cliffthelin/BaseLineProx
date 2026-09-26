"""Real-block-device safety validation for physical-hardware work
(see docs/design/ plan history - Track A of the real-hardware/GUI
parallel-tracks plan). Mirrors tools/qemu_harness_safety.py's
discipline for real disks instead of image files: every destructive
helper accepts only the dict validate_target_device() returns, never a
bare path, so validation cannot be skipped by construction (the same
pattern qemu_harness_safety.delete_validated_image uses).

Deliberately narrow scope: this module validates against an explicit,
hardcoded allowlist of (serial, size-range) pairs the operator has
already confirmed, out loud, are disposable for this project - not a
generic "any device" validator. Extending it to accept other devices
is out of scope here.

Real-hardware finding this module is built around: the two allowlisted
drives sit behind USB-NVMe bridge chips (Realtek RTL9210B-CG /
RTL9220DP), so /sys/class/block/<dev>/device/serial does not exist for
them - confirmed directly, not assumed. `udevadm info`'s ID_SERIAL_SHORT
property is the reliable source (the same one `lsblk -o SERIAL` itself
uses under the hood), so this module reads serials that way, not via a
raw sysfs file.
"""
import os
import stat
import subprocess


class PhysicalDeviceSafetyError(Exception):
    """Raised for any device this module refuses to accept as a
    destructive-operation target - never silently ignored."""


class Runner:
    """Injectable process/filesystem runner, matching this project's
    established Runner/FakeRunner pattern (baseline/lib/repair.py)."""

    def run(self, argv: list) -> str:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=15)
        return result.stdout

    def lstat(self, path: str):
        return os.lstat(path)

    def realpath(self, path: str) -> str:
        return os.path.realpath(path)

    def read_size_file(self, dev_name: str) -> str:
        with open(f"/sys/class/block/{dev_name}/size") as f:
            return f.read()


def _parse_udevadm_property(output: str, key: str) -> str | None:
    prefix = f"{key}="
    for line in output.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):]
    return None


def get_device_serial(runner: Runner, path: str) -> str | None:
    """Reads ID_SERIAL_SHORT via udevadm - see module docstring for why
    sysfs's own device/serial file is not used."""
    output = runner.run(["udevadm", "info", "--query=property", f"--name={path}"])
    return _parse_udevadm_property(output, "ID_SERIAL_SHORT")


def get_device_size_bytes(runner: Runner, resolved_path: str) -> int:
    dev_name = os.path.basename(resolved_path)
    sectors = int(runner.read_size_file(dev_name).strip())
    return sectors * 512


def get_boot_device_serial(runner: Runner) -> str | None:
    """Self-detects the machine's own boot device serial, so a caller
    can never target it even by passing the wrong path - findmnt to
    find the mounted root partition, resolve to its parent whole-disk
    device, then read that device's own serial - independent of
    whatever path string a caller passed for the intended target."""
    root_source = runner.run(["findmnt", "/", "-no", "SOURCE"]).strip()
    if not root_source:
        return None
    pkname = runner.run(["lsblk", "-no", "PKNAME", root_source]).strip()
    parent = f"/dev/{pkname}" if pkname else root_source
    return get_device_serial(runner, parent)


def validate_target_device(path: str, *, expected_serial: str, min_size_bytes: int,
                            max_size_bytes: int, runner: Runner = None) -> dict:
    """The one function every destructive helper in this module
    requires a result from. Refuses (raises PhysicalDeviceSafetyError)
    unless ALL of: the path is not a symlink; the resolved path is a
    block device; its serial matches expected_serial EXACTLY; its size
    falls within [min_size_bytes, max_size_bytes]; its serial does NOT
    match the machine's own boot-device serial."""
    runner = runner or Runner()

    if os.path.islink(path):
        raise PhysicalDeviceSafetyError(f"{path!r} is a symlink - refusing to follow it")

    resolved = runner.realpath(path)
    lst = runner.lstat(resolved)
    if not stat.S_ISBLK(lst.st_mode):
        raise PhysicalDeviceSafetyError(f"{resolved!r} is not a block device - refusing")

    actual_serial = get_device_serial(runner, resolved)
    if actual_serial != expected_serial:
        raise PhysicalDeviceSafetyError(
            f"{resolved!r} has serial {actual_serial!r}, expected exactly "
            f"{expected_serial!r} - refusing")

    boot_serial = get_boot_device_serial(runner)
    if boot_serial is not None and actual_serial == boot_serial:
        raise PhysicalDeviceSafetyError(
            f"{resolved!r} (serial {actual_serial!r}) matches this machine's own "
            f"boot device - refusing regardless of which path was passed")

    size_bytes = get_device_size_bytes(runner, resolved)
    if not (min_size_bytes <= size_bytes <= max_size_bytes):
        raise PhysicalDeviceSafetyError(
            f"{resolved!r} is {size_bytes} bytes, outside the expected range "
            f"[{min_size_bytes}, {max_size_bytes}] - refusing")

    return {"path": resolved, "serial": actual_serial, "size_bytes": size_bytes}


def validate_known_target(path: str, target_name: str, targets: dict, *,
                           runner: Runner = None) -> dict:
    """Validates against a caller-supplied allowlist dict (name ->
    {expected_serial, min_size_bytes, max_size_bytes}). This module
    never hardcodes real device serials itself, and does not read them
    from a bespoke local file either - real hardware identifiers
    belong in the persistence store's own durable data (this project's
    existing carrier-identity model - baseline/lib/testpersistence/
    identity.py's CarrierIdentity, for the synthetic experiment; a
    real, non-test analog for this real system), never scattered into
    an ad hoc repo-local config. See load_carrier_identities_from_
    persistence_manifest() below for how `targets` is meant to be
    produced in practice: read back from the persistence carrier's own
    recorded identity data, not maintained separately from it.

    The one unavoidable bootstrap exception: on the very first setup,
    before any persistence manifest exists to read from, the initial
    confirmed identity has to come from direct operator confirmation
    (the same kind of explicit, out-loud confirmation already given
    for this project's own two drives) - and that confirmation's
    result should be the FIRST thing written into the persistence
    manifest once it's created, not kept anywhere else afterward."""
    if target_name not in targets:
        raise PhysicalDeviceSafetyError(
            f"{target_name!r} is not one of the allowlisted targets "
            f"{sorted(targets)} - refusing")
    return validate_target_device(path, runner=runner, **targets[target_name])


def load_carrier_identities_from_persistence_manifest(manifest: dict) -> dict:
    """Adapts the persistence manifest's own recorded carrier-identity
    section into the `targets` shape validate_known_target() expects.
    Pure - no I/O, no Runner - the caller is responsible for having
    already read the manifest from the persistence carrier itself.
    Expected manifest shape (a real, non-test analog of TestPersistence's
    own manifest structure - deliberately its own, not the synthetic
    test-domain format, so real and synthetic identity data are never
    confused with each other):

        {"carrier_identities": {
            "<target-name>": {"serial": "...", "min_size_bytes": ...,
                               "max_size_bytes": ...}, ...}}
    """
    recorded = manifest.get("carrier_identities", {})
    return {
        name: {
            "expected_serial": entry["serial"],
            "min_size_bytes": entry["min_size_bytes"],
            "max_size_bytes": entry["max_size_bytes"],
        }
        for name, entry in recorded.items()
    }


def wipe_signatures(validated: dict, *, runner: Runner = None) -> None:
    """Wipes filesystem/RAID/LVM signatures on exactly the validated
    device - never accepts a bare path, only this module's own
    validated dict. wipefs clears recognized signature metadata only
    (not a full overwrite) - sufficient for a fresh partition table/
    install to proceed cleanly without a stale LVM/filesystem signature
    confusing subsequent tooling."""
    runner = runner or Runner()
    runner.run(["wipefs", "-a", validated["path"]])
