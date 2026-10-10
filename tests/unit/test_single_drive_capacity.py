"""Single-drive capacity policy: arithmetic tests never touch disks."""
import drive_installer as di
import pytest
import self_installer as si
from fake_runner import FakeRunner, FakeProc


def test_complete_single_drive_profile_fits_512gb_with_growth_reserved():
    size = 512_110_190_592
    plan = di.single_drive_plan(size, host_bytes=106 * 1024**3,
                                growth_percent=20)
    assert set(plan["volumes_gib"]) == {v[3] for v in di.BASELINE_VOLUMES}
    assert sum(plan["volumes_gib"].values()) * 1024**3 + plan["host_bytes"] + plan["growth_bytes"] + plan["safety_bytes"] <= size
    assert plan["growth_bytes"] >= size // 5
    assert all(plan["volumes_gib"][v[3]] >= v[1] for v in di.BASELINE_VOLUMES)


def test_measured_workload_cannot_be_shrunk_to_make_the_drive_appear_to_fit():
    required = {v[3]: v[1] * 1024**3 for v in di.BASELINE_VOLUMES}
    required["USER_PERSONAL"] = 350 * 1024**3
    with pytest.raises(ValueError, match="cannot fit"):
        di.single_drive_plan(512_110_190_592, host_bytes=106 * 1024**3,
                             required_bytes=required)


def test_same_complete_profile_is_available_to_each_independent_installer():
    first = si.single_drive_profile(512_110_190_592)
    second = si.single_drive_profile(512_110_190_592)
    assert first == second
    assert first["installer_sizes"] == {"lvm_maxroot": 32, "lvm_maxvz": 64, "lvm_swapsize": 4}
    assert first["storage"]["capacity_basis"] == "role-minimums"
    assert first["boot_reserve_bytes"] == 2 * 1024**3
    assert set(first["storage"]["volumes_gib"]) == {v[3] for v in di.BASELINE_VOLUMES}


def test_lvm_application_keeps_the_growth_reserve_and_refuses_short_capacity():
    profile = si.single_drive_profile(512_110_190_592)["storage"]
    sizes = profile["volumes_gib"]
    reserve = profile["growth_bytes"] + profile["safety_bytes"]
    needed = sum(sizes.values()) * 1024**3 + reserve
    runner = FakeRunner(command_responses=[
        (lambda a: "vgs" in a, FakeProc(0, str(needed - 1), "")),
    ])
    result = di.ensure_baseline_volumes(runner, planned_sizes_gib=sizes, reserve_bytes=reserve)
    assert all(not item.ok for item in result.values())
    assert not any(call[0] == "lvcreate" for call in runner.calls)


def test_existing_roles_do_not_require_allocating_their_capacity_again(monkeypatch):
    sizes = si.single_drive_profile(512_110_190_592)["storage"]["volumes_gib"]
    inventory = "\n".join(f"{v[0]} {sizes[v[3]] * 1024**3}" for v in di.BASELINE_VOLUMES)
    runner = FakeRunner(command_responses=[
        (lambda a: "vgs" in a, FakeProc(0, str(100 * 1024**3), "")),
        (lambda a: "lvs" in a, FakeProc(0, inventory, "")),
    ])
    monkeypatch.setattr(di, "ensure_volume", lambda *a, **k: di.CommandResult(True, "existing"))
    result = di.ensure_baseline_volumes(runner, planned_sizes_gib=sizes, reserve_bytes=100 * 1024**3)
    assert all(item.ok for item in result.values())


@pytest.mark.parametrize("inventory", ["baseline_user_admin unknown", "root 12\nroot 12", "root -1", "garbage"])
def test_untrusted_inventory_refuses_before_creating_any_role(inventory):
    sizes = si.single_drive_profile(512_110_190_592)["storage"]["volumes_gib"]
    runner = FakeRunner(command_responses=[
        (lambda a: "vgs" in a, FakeProc(0, str(450 * 1024**3), "")),
        (lambda a: "lvs" in a, FakeProc(0, inventory, "")),
    ])
    result = di.ensure_baseline_volumes(runner, planned_sizes_gib=sizes)
    assert all(not item.ok for item in result.values())
    assert not any(call[0] == "lvcreate" for call in runner.calls)


def test_installation_profile_reserves_room_for_ubuntu_desktop():
    import self_installer
    profile = self_installer.single_drive_profile(512110190592)
    assert profile['storage']['volumes_gib']['BASELINE'] >= 50
