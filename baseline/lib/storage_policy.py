"""Measured independent-drive policy. Saving a policy never provisions a drive."""
import json
import re
import uuid

import drive_installer as di
import self_installer

FORMAT = "baseline-independent-drive-v2"
LEGACY_FORMAT = "baseline-independent-drive-v1"
POLICY_PATH = "/mnt/SUBSTRATE/storage-policy.json"


class PolicyError(ValueError):
    pass


def build_policy(*, serial, size_bytes, required_bytes, bindings,
                 personas=di.DEFAULT_PERSONAS, growth_percent=20, migration_bytes=0, policy_format=FORMAT):
    if policy_format not in (FORMAT, LEGACY_FORMAT):
        raise PolicyError("unsupported independent-drive policy format")
    if not isinstance(serial, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", serial):
        raise PolicyError("a stable drive serial is required")
    if (not isinstance(personas, (tuple, list)) or not personas
            or any(not isinstance(p, str) or not re.fullmatch(r"[a-z][a-z0-9]{0,7}", p) for p in personas)
            or len(set(personas)) != len(personas)):
        raise PolicyError("personas must be distinct valid names")
    labels = {v[3] for v in di.baseline_volumes_for(tuple(personas))}
    if not isinstance(bindings, dict) or set(bindings) != labels:
        raise PolicyError("every role requires one backing identity")
    identities = set()
    for label, binding in bindings.items():
        if not isinstance(binding, dict) or set(binding) != {"serial", "uuid"} or binding["serial"] != serial:
            raise PolicyError("every role in an independent installation must be on its selected serial")
        try:
            identity = str(uuid.UUID(binding["uuid"]))
        except (ValueError, TypeError, AttributeError):
            raise PolicyError(f"{label}: filesystem UUID is invalid") from None
        if identity != binding["uuid"] or identity in identities or uuid.UUID(identity).int == 0:
            raise PolicyError("role filesystem identities must be canonical, nonzero and distinct")
        identities.add(identity)
    try:
        profile = self_installer.single_drive_profile(
            size_bytes, personas=tuple(personas), growth_percent=growth_percent,
            migration_bytes=migration_bytes, required_bytes=required_bytes,
            reserve_gui_runtime=policy_format == FORMAT)
    except ValueError as exc:
        raise PolicyError(str(exc)) from None
    return {"format": policy_format, "serial": serial, "size_bytes": size_bytes,
            "personas": list(personas), "growth_percent": growth_percent,
            "migration_bytes": migration_bytes, "required_bytes": dict(required_bytes),
            "bindings": {k: dict(v) for k, v in bindings.items()},
            "capacity": profile["storage"], "boot_verified": False}


def validate_policy(policy):
    if not isinstance(policy, dict) or set(policy) != {
            "format", "serial", "size_bytes", "personas", "growth_percent", "migration_bytes",
            "required_bytes", "bindings", "capacity", "boot_verified"} or policy["format"] not in (FORMAT, LEGACY_FORMAT):
        raise PolicyError("invalid independent-drive policy schema")
    rebuilt = build_policy(**{k: policy[k] for k in (
        "serial", "size_bytes", "personas", "growth_percent", "migration_bytes", "required_bytes", "bindings")},
        policy_format=policy["format"])
    if policy != rebuilt:
        raise PolicyError("policy capacity or verification claims disagree with its measurements")
    return policy


def save_policy(runner, path, policy):
    validate_policy(policy)
    runner.write_text_atomic(path, json.dumps(policy, sort_keys=True, indent=2) + "\n")


def load_policy(runner, path=POLICY_PATH):
    try:
        policy = json.loads(runner.read_text(path))
    except (OSError, ValueError):
        raise PolicyError("storage policy is missing or unreadable") from None
    return validate_policy(policy)


def measure_role(runner, *, mountpoint, expected_uuid):
    """Measure allocated and apparent bytes; sparse data must also fit after restore."""
    proc = runner.run(["findmnt", "-J", "--mountpoint", mountpoint,
                       "-o", "TARGET,SOURCE,FSTYPE,UUID"], timeout=15)
    try:
        mounts = json.loads(proc.stdout)["filesystems"]
        if (proc.returncode or len(mounts) != 1 or mounts[0]["target"] != mountpoint
                or not expected_uuid or mounts[0]["uuid"] != expected_uuid
                or mounts[0]["fstype"] != "ext4"):
            raise ValueError
    except (ValueError, KeyError, TypeError, IndexError):
        raise PolicyError("capacity measurement requires the expected mounted role filesystem") from None
    amounts = []
    for flags in ([], ["--apparent-size"]):
        measured = runner.run(["du", "-s", "-x", "-B1", *flags, "--", mountpoint], timeout=300)
        try:
            value = int(measured.stdout.split()[0])
            if measured.returncode or len(measured.stdout.strip().splitlines()) != 1 or value < 0:raise ValueError
        except (ValueError, IndexError, TypeError):
            raise PolicyError("role usage could not be completely measured") from None
        amounts.append(value)
    return max(amounts)


def verify_runtime(runner, path=POLICY_PATH):
    """First-boot read-only gate; policy files never stand in for mounted storage."""
    from single_drive_storage import inspect_target, _backing_disk
    policy = load_policy(runner, path)
    try:
        marker = json.loads(runner.read_text("/etc/baseline/independent-drive.json"))
        if marker["serial"] != policy["serial"] or marker["policy_path"] != path:
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        raise PolicyError("bootstrap serial/policy binding is missing or inconsistent") from None
    target = inspect_target(runner, expected_serial=policy["serial"], root_mount="/")
    if any(marker.get(key) != target[key] for key in ("root_uuid", "pv_uuid", "vg_uuid")):
        raise PolicyError("root/VG/PV identity differs from the provisioned bootstrap binding")
    if target["size_bytes"] != policy["size_bytes"]:
        raise PolicyError("boot disk capacity differs from the persisted policy")
    for _, _, _, label, mountpoint in di.baseline_volumes_for(tuple(policy["personas"])):
        proc = runner.run(["findmnt", "-J", "--mountpoint", mountpoint,
                           "-o", "TARGET,SOURCE,FSTYPE,UUID,OPTIONS"], timeout=15)
        try:
            mounts = json.loads(proc.stdout)["filesystems"]
            if proc.returncode or len(mounts) != 1:raise ValueError
            mount = mounts[0]
            options = set(mount["options"].split(","))
            required = set(di.mount_options_for(label).split(",")) - {"defaults"}
            if (mount["target"] != mountpoint or mount["fstype"] != "ext4"
                    or mount["uuid"] != policy["bindings"][label]["uuid"]
                    or "rw" not in options or not required.issubset(options)):
                raise ValueError
        except (ValueError, KeyError, TypeError, IndexError):
            raise PolicyError(f"{label} is missing, read-only, misrouted or lacks its role restrictions") from None
        _backing_disk(runner, mount["source"], policy["serial"])
        measured = runner.run(di.df_argv(mountpoint), timeout=15)
        usage = di.parse_df_output(measured.stdout) if measured.returncode == 0 else None
        if usage is None or usage["total_bytes"] < policy["required_bytes"][label]:
            raise PolicyError(f"{label} capacity is unknown or insufficient for its measured workload")
    return {"state": "storage_verified", "serial": policy["serial"],
            "roles": list(policy["bindings"]), "boot_verified": False}
