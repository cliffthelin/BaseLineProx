"""Review regressions for df4a84a and its inherited merge payload.

All drives, serial changes and commands are fakes. The original failures are
recorded in DR136; the fixes and passing results are documented in DR137.
"""
import install_plan as ip
import drive_enrollment as de
import pytest

from test_install_plan import BASE, PVE, EMPTY, baseline_disk, disk, discover, proxmox_disk
from test_drive_admin import FakePdsRunner
from test_lay_out_action import BLANK, Runner
from hitl_helpers import perform_confirmed, perform_with_origin


def test_review_autofill_requires_choice_between_multiple_empty_disks():
    found = discover(disk("sda", PVE), disk("sdb", BASE), disk("sdc", EMPTY))
    plan = ip.autofill(found)
    assert plan["storage"]["baseline"]["serial"] is None
    assert plan["storage"]["substrate"]["serial"] is None


def test_review_autofill_does_not_replace_ambiguous_existing_proxmox_with_empty_disk():
    found = discover(proxmox_disk(), proxmox_disk("sdc", EMPTY), baseline_disk(), disk("sde", "EMPTYREVIEW1"),
                     allowed={PVE, BASE, EMPTY, "EMPTYREVIEW1"})
    plan = ip.autofill(found)
    assert plan["storage"]["substrate"]["serial"] is None


def test_review_retain_refuses_missing_partuuid():
    carrier = baseline_disk()
    for partition in carrier["children"]:
        partition["partuuid"] = None
    found = discover(proxmox_disk(), carrier)
    assert ip.validate(ip.autofill(found), found)


@pytest.mark.parametrize("identity", ["", "bad-guid", "../device", 123, {}, "b0000000-0000-4000-8000-000000000000\n"])
def test_retain_never_compiles_malformed_partition_identity(identity):
    carrier = baseline_disk()
    carrier["children"][0]["partuuid"] = identity
    found = discover(proxmox_disk(), carrier)
    with pytest.raises(ip.PlanError):
        ip.compile_plan(ip.autofill(found), found)


def test_retain_rejects_duplicate_volume_names_in_plan():
    found = discover(proxmox_disk(), baseline_disk())
    plan = ip.autofill(found)
    plan["storage"]["baseline"]["volumes"].append(dict(plan["storage"]["baseline"]["volumes"][0]))
    assert ip.validate(plan, found)


def test_retain_rejects_duplicate_volume_names_on_drive():
    carrier = baseline_disk()
    duplicate = dict(carrier["children"][0], name="sdb9", partuuid="c0000000-0000-4000-8000-000000000000")
    carrier["children"].append(duplicate)
    found = discover(proxmox_disk(), carrier)
    plan = ip.autofill(found)
    listed = plan["storage"]["baseline"]["volumes"]
    plan["storage"]["baseline"]["volumes"] = list({v["name"]: v for v in listed}.values())
    assert ip.validate(plan, found)


def test_review_retain_refuses_colliding_partuuids_on_other_enrolled_disk():
    found = discover(proxmox_disk(), baseline_disk(), baseline_disk("sdc", EMPTY))
    plan = ip.autofill(discover(proxmox_disk(), baseline_disk()))
    assert ip.validate(plan, found)


@pytest.mark.parametrize("other_serial", ["NOTENROLLEDCOPY1", "SN2118", None])
def test_cloned_partuuids_on_hidden_disks_cannot_redirect_retained_mounts(other_serial):
    found = discover(proxmox_disk(), baseline_disk(), baseline_disk("sdc", other_serial))
    plan = ip.autofill(discover(proxmox_disk(), baseline_disk()))
    with pytest.raises(ip.PlanError, match="not valid"):
        ip.compile_plan(plan, found)


def test_case_differences_cannot_hide_cloned_partuuid():
    clone = baseline_disk("sdc", "NOTENROLLEDCOPY1")
    clone["children"][0]["partuuid"] = clone["children"][0]["partuuid"].upper()
    found = discover(proxmox_disk(), baseline_disk(), clone)
    plan = ip.autofill(discover(proxmox_disk(), baseline_disk()))
    assert ip.validate(plan, found)


def test_repeated_listing_of_same_partition_does_not_create_false_collision():
    import json
    from test_install_plan import ALLOWED, BOOT
    carrier = baseline_disk()
    # A device can appear more than once under a multi-parent lsblk tree.
    roots = [proxmox_disk(), carrier, dict(carrier)]
    found = ip.discover(json.dumps({"blockdevices": roots}), allowed_serials=ALLOWED, boot_serial=BOOT,
                        is_installer_uuid=lambda guid: True)
    plan = ip.autofill(discover(proxmox_disk(), baseline_disk()))
    assert ip.validate(plan, found) == []


def test_install_plan_refuses_unknown_boot_identity_instead_of_offering_boot_disk():
    import json
    with pytest.raises(ip.PlanError, match="boot"):
        ip.discover(json.dumps({"blockdevices": [proxmox_disk(), baseline_disk()]}),
                    allowed_serials={BASE, PVE}, boot_serial=None, is_installer_uuid=lambda guid: False)


@pytest.mark.parametrize("replacement", ["NOTENROLLEDREVIEW1", PVE])
def test_review_layout_refuses_serial_change_after_confirmation(monkeypatch, replacement):
    import drive_guard as dg
    monkeypatch.setattr(dg, "_default_run", lambda argv: (0, BLANK))
    pds_runner = FakePdsRunner(size_bytes=512_110_190_592, drive_table=BLANK)

    class SwappingRunner(Runner):
        def run(self, argv, timeout=10):
            # The action's first command occurs after web/HITL and _prepare.
            if argv[0] == "lsblk":
                pds_runner.serial = replacement
            return super().run(argv, timeout)

    runner = SwappingRunner()
    result = perform_confirmed(runner, "lay_out_baseline_drive", {"device_path": "/dev/sdb"},
                               pds_runner=pds_runner)
    writes = [c for c in runner.calls if c[0] in ("wipefs", "sgdisk", "mkfs.ext4")]
    assert not writes, f"confirmed drive was replaced; destructive fake commands still ran: {writes}"
    assert not result.ok


def test_layout_stops_if_drive_is_replaced_between_destructive_steps(monkeypatch):
    import drive_guard as dg
    monkeypatch.setattr(dg, "_default_run", lambda argv: (0, BLANK))
    pds_runner = FakePdsRunner(size_bytes=512_110_190_592, drive_table=BLANK)

    class SwappingRunner(Runner):
        def run(self, argv, timeout=10):
            result = super().run(argv, timeout)
            if argv[0] == "wipefs":
                pds_runner.serial = PVE
            return result

    runner = SwappingRunner()
    result = perform_confirmed(runner, "lay_out_baseline_drive", {"device_path": "/dev/sdb"},
                               pds_runner=pds_runner)
    assert not result.ok
    assert [c[0] for c in runner.calls if c[0] in ("wipefs", "sgdisk", "mkfs.ext4")] == ["wipefs"]


def test_review_enrollment_refuses_when_boot_identity_is_unknown():
    pds_runner = FakePdsRunner(serial="UNKNOWNBOOTREVIEW1", findmnt_root="")
    result = perform_with_origin(None, "enroll_drive",
                               {"device_path": "/dev/sdc", "confirm_serial": "UNKNOWNBOOTREVIEW1"},
                               pds_runner=pds_runner)
    assert not result.ok and "boot" in result.detail
    assert "UNKNOWNBOOTREVIEW1" not in de.enrolled_serials()


@pytest.mark.parametrize("boot_serial", [None, "", "\n"])
def test_device_gate_refuses_unreadable_boot_serial(boot_serial):
    import physical_device_safety as pds
    runner = FakePdsRunner(boot_serial=boot_serial)
    # Return genuinely missing/empty udev identity rather than str(None).
    original = runner.run
    def run(argv):
        if argv[0] == "udevadm" and argv[-1].endswith("nvme0n1"):
            return "" if boot_serial is None else f"ID_SERIAL_SHORT={boot_serial}\n"
        return original(argv)
    runner.run = run
    with pytest.raises(pds.PhysicalDeviceSafetyError, match="boot"):
        pds.validate_target_device("/dev/sdb", expected_serial=BASE, min_size_bytes=0, runner=runner)
