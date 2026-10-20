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


# --- grow-on-demand (operator, 2026-10-11: "1 GB each volume only grows if actually used and needed") ----------------------------

GIB = 1024 ** 3
SMALL = {"lvm_maxroot": 16, "lvm_maxvz": 8, "lvm_swapsize": 2}


def _measured(**overrides):
    required = {v[3]: 0 for v in di.BASELINE_VOLUMES}
    required.update(INSTALLER_CACHE=6 * GIB, USER_ADMIN=262144, BASELINE=139264)
    required.update(overrides)
    return required


def test_grow_on_demand_starts_every_role_at_its_measured_need_and_at_least_one_gib():
    plan = di.single_drive_plan(64 * GIB, host_bytes=30 * GIB, required_bytes=_measured(), grow_on_demand=True)
    assert plan["capacity_basis"] == "grow-on-demand"
    assert plan["volumes_gib"]["INSTALLER_CACHE"] == 6
    assert all(plan["volumes_gib"][label] == 1 for label in plan["volumes_gib"] if label != "INSTALLER_CACHE")
    assert plan["unallocated_bytes"] > 20 * GIB                 # the rest stays free for volumes to grow into


def test_grow_on_demand_still_refuses_a_drive_that_cannot_hold_the_host_the_measured_roles_and_the_growth_reserve():
    with pytest.raises(ValueError, match="cannot fit"):
        di.single_drive_plan(40 * GIB, host_bytes=30 * GIB, required_bytes=_measured(), grow_on_demand=True)
    with pytest.raises(ValueError, match="cannot fit"):
        di.single_drive_plan(64 * GIB, host_bytes=30 * GIB, required_bytes=_measured(USER_PERSONAL=40 * GIB), grow_on_demand=True)


def test_without_grow_on_demand_the_fixed_minimum_plan_is_unchanged_for_the_real_drive():
    size = 512_110_190_592
    assert (di.single_drive_plan(size, host_bytes=106 * GIB)
            == di.single_drive_plan(size, host_bytes=106 * GIB, grow_on_demand=False))
    assert di.single_drive_plan(size, host_bytes=106 * GIB)["capacity_basis"] == "role-minimums"
    with pytest.raises(ValueError, match="cannot fit"):
        di.single_drive_plan(64 * GIB, host_bytes=30 * GIB, required_bytes=_measured())


def test_a_grow_profile_uses_the_measured_host_sizes_not_the_real_drive_preset():
    profile = si.single_drive_profile(64 * GIB, required_bytes=_measured(), grow_on_demand=True, installer_sizes=SMALL,
                                      host_bytes_measured=28 * GIB)
    assert profile["installer_sizes"] == SMALL and profile["thin_data_min_bytes"] == 0
    assert profile["storage"]["host_bytes"] == 30 * GIB


def test_ensure_volumes_accepts_one_gib_roles_only_in_grow_on_demand_mode(monkeypatch):
    sizes = {v[3]: 1 for v in di.BASELINE_VOLUMES}
    sizes["INSTALLER_CACHE"] = 6
    inventory = ""                                                  # nothing exists yet
    runner = FakeRunner(command_responses=[
        (lambda a: "vgs" in a, FakeProc(0, str(100 * GIB), "")),
        (lambda a: "lvs" in a, FakeProc(0, inventory, "")),
    ])
    monkeypatch.setattr(di, "ensure_volume", lambda *a, **k: di.CommandResult(True, "created"))
    refused = di.ensure_baseline_volumes(runner, planned_sizes_gib=sizes, reserve_bytes=10 * GIB)
    assert all(not item.ok and "minimum" in item.detail for item in refused.values())
    accepted = di.ensure_baseline_volumes(runner, planned_sizes_gib=sizes, reserve_bytes=10 * GIB, grow_on_demand=True)
    assert all(item.ok for item in accepted.values())


def test_a_renamed_group_is_found_by_the_device_node_behind_the_old_name(tmp_path):
    import single_drive_storage as sds
    sysfs = tmp_path / "sys"
    (sysfs / "dm-0" / "dm").mkdir(parents=True)
    (sysfs / "dm-0" / "dm" / "name").write_text("baseline_abc-root\n")
    node = tmp_path / "dm-0"
    node.write_text("")
    link = tmp_path / "pve-root"
    link.symlink_to(node)
    assert sds.current_device_name(str(link), sysfs=str(sysfs)) == "/dev/mapper/baseline_abc-root"
    assert sds.current_device_name("/dev/mapper/nowhere-root", sysfs=str(sysfs)) == "/dev/mapper/nowhere-root"
