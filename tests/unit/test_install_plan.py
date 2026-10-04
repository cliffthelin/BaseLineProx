"""Installer plan: discover drives by serial and volumes by PARTUUID, autofill an editable plan, validate the edits,
and compile them into the parameters the existing provisioning stages take (queue rows 72/76, 2026-10-03).

Pure functions over `lsblk -J -b` text. Nothing here runs a command, opens a device or provisions anything; compiled
stages are what a later, separately confirmed run would execute. Unit-tested only - not real hardware."""
import copy
import json

import pytest

import install_plan as ip

PVE, BASE, EMPTY, OTHER, BOOT = "FD01N6557110C271B", "MD89N41071210AP4E", "S6WRNS0TA12638A", "WCV00YLT", "SN2118"
ALLOWED = frozenset({PVE, BASE, EMPTY, OTHER})
INSTALLER_GUID = "8afe8468-ea73-4944-8842-0cbbe4a82d16"


def disk(name, serial, *, size=512_110_190_592, ptuuid=None, children=(), model="PC601 NVMe SK hynix 512GB",
         fstype=None, mountpoint=None):
    return {"name": name, "type": "disk", "size": size, "model": model, "serial": serial, "ptuuid": ptuuid,
            "partuuid": None, "partlabel": None, "fstype": fstype, "uuid": None, "label": None,
            "mountpoint": mountpoint, **({"children": list(children)} if children else {})}


def part(name, partlabel, partuuid, *, fstype="ext4", size=10 * 1024**3, mountpoint=None, children=()):
    return {"name": name, "type": "part", "size": size, "model": None, "serial": None, "ptuuid": None,
            "partuuid": partuuid, "partlabel": partlabel, "fstype": fstype, "uuid": f"fs-{partuuid}",
            "label": partlabel and partlabel[:16], "mountpoint": mountpoint,
            **({"children": list(children)} if children else {})}


BASELINE_NAMES = ["BASELINE", "INSTALLER_CACHE", "SESSION_TEMP", "SUBSTRATE", "USER_ADMIN", "USER_PERSONAL",
                  "APPDATA_ADMIN", "APPDATA_PERSONAL"]


def baseline_disk(name="sdb", serial=BASE, names=BASELINE_NAMES, prefix="b", ptuuid=INSTALLER_GUID, mounted=False):
    return disk(name, serial, ptuuid=ptuuid, model="PC401 NVMe SK hynix 512GB", children=[
        part(f"{name}{i + 1}", label, f"{prefix}{i:07d}-0000-4000-8000-000000000000",
             mountpoint=f"/mnt/{label}" if mounted else None) for i, label in enumerate(names)])


def proxmox_disk(name="sda", serial=PVE):
    lvs = [{"name": "pve-root", "type": "lvm", "size": 1, "fstype": "ext4", "mountpoint": None},
           {"name": "pve-data_tmeta", "type": "lvm", "size": 1, "fstype": None, "mountpoint": None}]
    return disk(name, serial, ptuuid="11111111-2222-3333-4444-555555555555", children=[
        part(f"{name}1", None, "aaaa0001-0000-4000-8000-000000000000", fstype=None),
        part(f"{name}2", None, "aaaa0002-0000-4000-8000-000000000000", fstype="vfat"),
        part(f"{name}3", None, "aaaa0003-0000-4000-8000-000000000000", fstype="LVM2_member", children=lvs)])


def lsblk(*disks):
    return json.dumps({"blockdevices": list(disks)})


def discover(*disks, allowed=ALLOWED, installer=frozenset({INSTALLER_GUID})):
    return ip.discover(lsblk(*disks), allowed_serials=allowed, boot_serial=BOOT,
                       is_installer_uuid=lambda guid: guid in installer)


STANDARD = (proxmox_disk(), baseline_disk(), disk("nvme0n1", BOOT, children=[part("nvme0n1p1", None, "boot-1")]))


# --- discovery --------------------------------------------------------------------------------

def test_the_discovery_command_reads_json_with_byte_sizes_and_every_identity_column():
    argv = ip.lsblk_argv()
    assert argv[:3] == ["lsblk", "-J", "-b"]
    for column in ("SERIAL", "PTUUID", "PARTUUID", "PARTLABEL", "FSTYPE", "UUID", "MOUNTPOINT"):
        assert column in argv[-1].split(",")


def test_drives_are_identified_by_serial_and_classified_by_what_they_hold():
    found = discover(*STANDARD, disk("sdc", EMPTY))
    by_serial = {d["serial"]: d for d in found["drives"]}
    assert by_serial[PVE]["state"] == "proxmox"
    assert by_serial[BASE]["state"] == "baseline" and by_serial[BASE]["installer_made"] is True
    assert by_serial[EMPTY]["state"] == "empty"


def test_the_boot_drive_is_never_discovered_even_if_allowed():
    found = discover(*STANDARD, allowed=ALLOWED | {BOOT})
    assert BOOT not in {d["serial"] for d in found["drives"]} | {d["serial"] for d in found["unenrolled"]}


def test_baseline_volumes_are_named_by_partition_label_and_identified_by_partuuid():
    volumes = {v["name"]: v for v in discover(*STANDARD)["drives"][1]["volumes"]}
    assert set(volumes) == set(BASELINE_NAMES)
    assert volumes["USER_ADMIN"]["partuuid"] == "b0000004-0000-4000-8000-000000000000"
    assert volumes["USER_ADMIN"]["fs_uuid"] == "fs-b0000004-0000-4000-8000-000000000000"


def test_legacy_partition_names_are_recognised_under_their_current_names():
    legacy = ["BASELINE", "INSTALLER_CACHE", "SESSION_TEMP", "SUBSTRATE_PERSISTENCE", "USER_PERSISTENCE_ADMIN"]
    found = discover(baseline_disk(names=legacy))
    names = {v["name"]: v["partlabel"] for v in found["drives"][0]["volumes"]}
    assert names["SUBSTRATE"] == "SUBSTRATE_PERSISTENCE" and names["USER_ADMIN"] == "USER_PERSISTENCE_ADMIN"


def test_a_drive_holding_other_data_is_classified_as_data_and_its_contents_are_not_listed():
    found = discover(disk("sdd", OTHER, children=[part("sdd1", "TV", "cccc0001", fstype="ntfs")]))
    drive = found["drives"][0]
    assert drive["state"] == "data" and drive["volumes"] == []


def test_drives_that_are_not_enrolled_are_listed_only_by_serial_model_and_size():
    found = discover(*STANDARD, disk("sdc", "NOTENROLLED1", children=[part("sdc1", "secret", "dddd0001")]))
    assert found["unenrolled"] == [{"serial": "NOTENROLLED1", "model": "PC601 NVMe SK hynix 512GB",
                                    "size_bytes": 512_110_190_592}]


def test_a_drive_without_a_serial_is_counted_but_never_offered():
    found = discover(*STANDARD, disk("sdz", None), disk("sdy", ""))
    assert found["unidentified"] == 2
    assert all(d["serial"] for d in found["drives"] + found["unenrolled"])


def test_a_mounted_drive_is_marked_mounted():
    found = discover(baseline_disk(mounted=True))
    assert found["drives"][0]["mounted"] is True


@pytest.mark.parametrize("text", ["", "not json", "[]", '{"blockdevices": "x"}', '{"other": []}'])
def test_unreadable_discovery_output_is_refused_not_guessed(text):
    with pytest.raises(ip.PlanError):
        ip.discover(text, allowed_serials=ALLOWED, boot_serial=BOOT, is_installer_uuid=lambda g: False)


def test_a_kernel_name_is_reported_only_as_the_current_path_never_as_identity():
    drive = discover(*STANDARD)["drives"][0]
    assert drive["path_now"] == "/dev/sda"
    plan = ip.autofill(discover(*STANDARD))
    assert "/dev/" not in json.dumps(plan)


# --- autofill -----------------------------------------------------------------------------------

def test_autofill_keeps_the_proxmox_drive_and_retains_the_baseline_drive_volume_by_volume():
    plan = ip.autofill(discover(*STANDARD))
    assert plan["storage"]["substrate"] == {"serial": PVE, "action": "keep"}
    baseline = plan["storage"]["baseline"]
    assert baseline["serial"] == BASE and baseline["action"] == "retain" and baseline["erase_existing"] is False
    assert {v["name"]: v["partuuid"] for v in baseline["volumes"]}["USER_PERSONAL"] == \
        "b0000005-0000-4000-8000-000000000000"
    assert ip.validate(plan, discover(*STANDARD)) == []


def test_empty_drives_require_explicit_role_choices_before_installing_or_laying_out():
    found = discover(disk("sda", PVE), disk("sdb", BASE))
    plan = ip.autofill(found)
    assert plan["storage"]["substrate"] == {"serial": None, "action": None}
    assert plan["storage"]["baseline"]["serial"] is None
    with pytest.raises(ip.PlanError):
        ip.compile_plan(plan, found)
    plan["storage"]["substrate"] = {"serial": PVE, "action": "install"}
    plan["storage"]["baseline"].update(serial=BASE, action="lay_out")
    assert plan["storage"]["substrate"] == {"serial": PVE, "action": "install"}
    assert plan["storage"]["baseline"]["serial"] == BASE and plan["storage"]["baseline"]["action"] == "lay_out"
    assert plan["storage"]["baseline"]["volumes"] == []
    assert ip.validate(plan, found) == []


def test_autofill_never_chooses_a_drive_that_holds_other_data():
    found = discover(disk("sdd", OTHER, children=[part("sdd1", "TV", "cccc0001", fstype="ntfs")]))
    plan = ip.autofill(found)
    assert plan["storage"]["substrate"]["serial"] is None and plan["storage"]["baseline"]["serial"] is None
    assert any("choose" in note for note in plan["notes"])


def test_autofill_does_not_guess_between_two_baseline_drives():
    found = discover(proxmox_disk(), baseline_disk(), baseline_disk("sdc", EMPTY, prefix="c"))
    plan = ip.autofill(found)
    assert plan["storage"]["baseline"]["serial"] is None
    assert any(BASE in note and EMPTY in note for note in plan["notes"])


def test_autofill_fills_the_os_and_the_application_choices_with_editable_defaults():
    plan = ip.autofill(discover(*STANDARD))
    assert plan["environment"] == {"os": "ubuntu-24.04", "variant": "desktop", "name": "baseline-desktop"}
    assert plan["applications"]["apps"] == ["vscode", "spotify", "chrome", "chatgpt", "claude"]
    assert plan["applications"]["run_as"] == "baseline-admin"


# --- validation of operator edits ------------------------------------------------------------------

def edited(plan, path, value):
    plan = copy.deepcopy(plan)
    *parents, key = path
    target = plan
    for p in parents:
        target = target[p]
    target[key] = value
    return plan


@pytest.fixture
def standard():
    found = discover(*STANDARD, disk("sdc", EMPTY), disk("sdd", OTHER, children=[part("sdd1", "TV", "c1", fstype="ntfs")]))
    return found, ip.autofill(found)


def errors_for(standard, path, value):
    found, plan = standard
    return ip.validate(edited(plan, path, value), found)


def test_an_unknown_or_missing_field_is_refused(standard):
    found, plan = standard
    assert ip.validate({**plan, "extra": 1}, found)
    assert ip.validate({k: v for k, v in plan.items() if k != "applications"}, found)
    assert errors_for(standard, ["storage", "baseline", "mountpoint"], "/x")


def test_a_device_path_is_never_accepted_in_place_of_a_serial(standard):
    assert errors_for(standard, ["storage", "baseline", "serial"], "/dev/sdb")


def test_a_drive_that_is_not_enrolled_and_discovered_cannot_be_chosen(standard):
    assert errors_for(standard, ["storage", "substrate", "serial"], "NOTPRESENT1")


def test_the_same_drive_cannot_be_both_proxmox_and_baseline(standard):
    assert errors_for(standard, ["storage", "baseline", "serial"], PVE)


def test_proxmox_is_never_installed_over_a_drive_holding_data(standard):
    found, plan = standard
    for serial in (OTHER, BASE):
        plan2 = edited(edited(plan, ["storage", "substrate", "serial"], serial), ["storage", "substrate", "action"], "install")
        assert ip.validate(plan2, found), serial


def test_proxmox_may_be_installed_on_an_empty_drive(standard):
    found, plan = standard
    plan2 = edited(edited(plan, ["storage", "substrate", "serial"], EMPTY), ["storage", "substrate", "action"], "install")
    assert ip.validate(plan2, found) == []


def test_keep_needs_a_drive_that_actually_holds_proxmox(standard):
    assert errors_for(standard, ["storage", "substrate", "serial"], EMPTY)


def test_retaining_volumes_needs_the_exact_partuuids_discovered_on_that_drive(standard):
    found, plan = standard
    volumes = copy.deepcopy(plan["storage"]["baseline"]["volumes"])
    volumes[4]["partuuid"] = "ffffffff-0000-4000-8000-000000000000"
    assert ip.validate(edited(plan, ["storage", "baseline", "volumes"], volumes), found)
    assert ip.validate(edited(plan, ["storage", "baseline", "volumes"], volumes[:-1]), found)


def test_retaining_a_drive_that_is_missing_a_required_volume_points_to_repair():
    found = discover(proxmox_disk(), baseline_disk(names=BASELINE_NAMES[:5]))
    errors = ip.validate(ip.autofill(found), found)
    assert any("USER_PERSONAL" in e and "repair" in e for e in errors)


def test_laying_out_over_existing_baseline_volumes_needs_an_explicit_erase(standard):
    found, plan = standard
    plan2 = edited(edited(plan, ["storage", "baseline", "action"], "lay_out"), ["storage", "baseline", "volumes"], [])
    assert any("erase" in e for e in ip.validate(plan2, found))
    plan3 = edited(plan2, ["storage", "baseline", "erase_existing"], True)
    assert ip.validate(plan3, found) == []


def test_erasing_existing_volumes_is_refused_unless_the_installer_made_the_drive():
    found = discover(proxmox_disk(), baseline_disk(ptuuid="22222222-2222-4222-8222-222222222222"))
    plan = ip.autofill(found)
    plan = edited(edited(plan, ["storage", "baseline", "action"], "lay_out"), ["storage", "baseline", "volumes"], [])
    plan = edited(plan, ["storage", "baseline", "erase_existing"], True)
    assert any("installer" in e for e in ip.validate(plan, found))


def test_a_mounted_drive_is_never_laid_out_or_installed_over():
    found = discover(proxmox_disk(), baseline_disk(mounted=True, ptuuid=INSTALLER_GUID))
    plan = ip.autofill(found)
    assert ip.validate(plan, found) == []              # retaining a mounted drive is fine
    plan = edited(edited(plan, ["storage", "baseline", "action"], "lay_out"), ["storage", "baseline", "volumes"], [])
    plan = edited(plan, ["storage", "baseline", "erase_existing"], True)
    assert any("mounted" in e for e in ip.validate(plan, found))


@pytest.mark.parametrize("personas", [[], ["personal"], ["admin", "admin"], ["admin", "Work"], ["admin", "toolongname"],
                                      "admin", ["admin", "../x"]])
def test_personas_are_checked(standard, personas):
    assert errors_for(standard, ["storage", "baseline", "personas"], personas)


@pytest.mark.parametrize("path,value", [
    (["environment", "os"], "windows-11"), (["environment", "os"], "debian-13"),
    (["environment", "variant"], "kiosk"), (["environment", "name"], "Bad Name"), (["environment", "name"], ""),
    (["applications", "apps"], []), (["applications", "apps"], ["vscode", "vscode"]),
    (["applications", "apps"], ["notepad"]), (["applications", "run_as"], "root"),
    (["applications", "cache"], "relative/path"), (["applications", "data"], "/var/lib/baseline-app-cache/x"),
    (["applications", "data"], "/home/{{ evil }}"),
])
def test_os_and_application_choices_are_checked(standard, path, value):
    assert errors_for(standard, path, value)


def test_validation_reports_every_problem_not_just_the_first(standard):
    found, plan = standard
    plan = edited(edited(plan, ["environment", "os"], "windows-11"), ["applications", "apps"], [])
    assert len(ip.validate(plan, found)) >= 2


def test_a_plan_is_checked_against_fresh_discovery_so_a_swapped_drive_is_caught(standard):
    found, plan = standard
    swapped = discover(proxmox_disk(), baseline_disk(prefix="z"))     # same serial, re-laid-out since autofill
    assert ip.validate(plan, swapped)


# --- compilation into the existing stages -----------------------------------------------------------

def test_compile_refuses_an_invalid_plan(standard):
    found, plan = standard
    with pytest.raises(ip.PlanError) as exc:
        ip.compile_plan(edited(plan, ["environment", "os"], "windows-11"), found)
    assert exc.value.errors


def test_retained_volumes_compile_to_partuuid_mounts_with_each_volumes_own_options(standard):
    found, plan = standard
    stages = ip.compile_plan(plan, found)
    mounts = {m["name"]: m for m in stages["baseline_drive"]["mounts"]}
    assert stages["baseline_drive"]["action"] == "retain" and stages["baseline_drive"]["expected_serial"] == BASE
    cache = mounts["INSTALLER_CACHE"]
    assert cache["fstab"] == ("PARTUUID=b0000001-0000-4000-8000-000000000000 /mnt/INSTALLER_CACHE ext4 "
                              "defaults,nosuid,nodev,noexec 0 2")
    assert mounts["USER_ADMIN"]["mountpoint"] == "/mnt/USER_ADMIN"
    assert all(m["fstab"].startswith("PARTUUID=") for m in mounts.values())


def test_installing_proxmox_compiles_to_the_existing_self_installer_action_bound_by_serial(standard):
    found, plan = standard
    plan = edited(edited(plan, ["storage", "substrate", "serial"], EMPTY), ["storage", "substrate", "action"], "install")
    stages = ip.compile_plan(plan, found)
    assert stages["substrate"] == {"action": "install", "drive_action": "build_self_installer",
                                   "params": {"expected_serial": EMPTY}}


def test_laying_out_compiles_to_the_existing_layout_action_and_defers_mounts_until_partuuids_exist():
    found = discover(proxmox_disk(), disk("sdb", BASE))
    stages = ip.compile_plan(ip.autofill(found), found)
    assert stages["baseline_drive"]["drive_action"] == "lay_out_baseline_drive"
    assert stages["baseline_drive"]["expected_serial"] == BASE
    assert stages["baseline_drive"]["mounts"] == []
    assert any("discover" in step for step in stages["after"])


def test_environment_and_applications_compile_to_the_existing_recipe_and_tasker_inputs(standard):
    found, plan = standard
    stages = ip.compile_plan(plan, found)
    assert stages["environment"] == {"name": "baseline-desktop", "desktop": True, "base": "ubuntu-noble-20260926"}
    apps = stages["applications"]
    assert apps["apps"] == ["vscode", "spotify", "chrome", "chatgpt", "claude"]
    assert apps["cache"] == "/var/lib/baseline-app-cache"
    assert apps["generation_root"] == "/var/lib/baseline-apps/generations"
    assert apps["data"] == "/home/baseline-admin/baseline-managed-apps"


def test_compiled_stages_state_plainly_that_nothing_ran(standard):
    found, plan = standard
    stages = ip.compile_plan(plan, found)
    assert stages["executed"] is False
    assert stages["not_yet_connected"]


# --- the baseline-install-plan command ---------------------------------------------------------------

def run_main(argv, tmp_path, *disks):
    out = []
    code = ip.main(argv, read_listing=lambda: lsblk(*disks), boot_serial=BOOT, allowed_serials=ALLOWED,
                   is_installer_uuid=lambda guid: guid == INSTALLER_GUID, print_fn=out.append)
    return code, "\n".join(out)


def test_the_command_autofills_a_plan_that_then_validates_and_compiles(tmp_path):
    code, text = run_main(["autofill"], tmp_path, *STANDARD)
    assert code == 0 and json.loads(text)["format"] == ip.FORMAT
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(text)
    assert run_main(["validate", str(plan_file)], tmp_path, *STANDARD) == (0, "plan is valid against the drives present now")
    code, text = run_main(["compile", str(plan_file)], tmp_path, *STANDARD)
    assert code == 0 and json.loads(text)["executed"] is False


def test_the_command_reports_every_problem_and_fails_when_the_drives_changed(tmp_path):
    _, text = run_main(["autofill"], tmp_path, *STANDARD)
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(text)
    code, text = run_main(["compile", str(plan_file)], tmp_path, proxmox_disk(), baseline_disk(prefix="z"))
    assert code == 1 and text.count("not on this drive now") == len(BASELINE_NAMES)


def test_the_command_refuses_a_plan_file_that_is_not_json(tmp_path):
    bad = tmp_path / "plan.json"
    bad.write_text("{not json")
    code, text = run_main(["validate", str(bad)], tmp_path, *STANDARD)
    assert code == 1 and "not JSON" in text


def test_the_discover_command_prints_what_it_found(tmp_path):
    code, text = run_main(["discover"], tmp_path, *STANDARD)
    assert code == 0 and {d["serial"] for d in json.loads(text)["drives"]} == {PVE, BASE}
