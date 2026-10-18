"""The v3 (grow-on-demand) policy format, and that v1/v2 policies on installed drives still validate exactly as before."""
import pytest

import drive_installer as di
import storage_policy as sp

SERIAL = "BLREHEARSAL01"
GIB = 1024 ** 3
SIZES = {"lvm_maxroot": 16, "lvm_maxvz": 8, "lvm_swapsize": 2}
IDS = ["11111111-1111-4111-8111-11111111111%x" % i for i in range(8)]


def bindings(personas=di.DEFAULT_PERSONAS):
    labels = [v[3] for v in di.baseline_volumes_for(tuple(personas))]
    return {label: {"serial": SERIAL, "uuid": IDS[i]} for i, label in enumerate(labels)}


def required():
    out = {v[3]: 0 for v in di.BASELINE_VOLUMES}
    out["INSTALLER_CACHE"] = 6 * GIB
    return out


def grow_policy():
    return sp.build_policy(serial=SERIAL, size_bytes=64 * GIB, required_bytes=required(), bindings=bindings(),
                           policy_format=sp.GROW_FORMAT, installer_sizes=SIZES, host_bytes=28 * GIB)


def test_a_grow_policy_round_trips_through_validation_and_records_the_measured_host():
    policy = grow_policy()
    assert policy["format"] == sp.GROW_FORMAT and policy["installer_sizes"] == SIZES and policy["host_bytes"] == 28 * GIB
    assert policy["capacity"]["capacity_basis"] == "grow-on-demand"
    assert sp.validate_policy(policy) == policy


def test_a_grow_policy_cannot_be_edited_to_claim_a_different_capacity_or_drop_its_measurements():
    policy = grow_policy()
    policy["capacity"] = dict(policy["capacity"], volumes_gib=dict(policy["capacity"]["volumes_gib"], USER_ADMIN=500))
    with pytest.raises(sp.PolicyError):
        sp.validate_policy(policy)
    missing = {k: v for k, v in grow_policy().items() if k != "host_bytes"}
    with pytest.raises(sp.PolicyError):
        sp.validate_policy(missing)


def test_the_earlier_formats_still_validate_and_cannot_carry_the_grow_fields():
    for fmt in (sp.FORMAT, sp.LEGACY_FORMAT):
        policy = sp.build_policy(serial="SYNTHDRIVEB00002", size_bytes=512_110_190_592,
                                 required_bytes={v[3]: 0 for v in di.BASELINE_VOLUMES}, bindings=bindings_for("SYNTHDRIVEB00002"),
                                 policy_format=fmt)
        assert sp.validate_policy(policy) == policy and "installer_sizes" not in policy
        assert policy["capacity"]["capacity_basis"] == "measured-workload"
    with pytest.raises(sp.PolicyError):
        sp.build_policy(serial=SERIAL, size_bytes=512_110_190_592, required_bytes=required(), bindings=bindings(),
                        policy_format=sp.FORMAT, installer_sizes=SIZES, host_bytes=1)


def bindings_for(serial):
    labels = [v[3] for v in di.BASELINE_VOLUMES]
    return {label: {"serial": serial, "uuid": IDS[i]} for i, label in enumerate(labels)}
