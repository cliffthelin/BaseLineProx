"""Where exactly one of something is needed and more than one is found, nothing is silently chosen: it is reported with everything that was found."""
import json

import pytest

import cardinality as card


class Proc:
    def __init__(self, out="", code=0, err=""):
        self.stdout, self.returncode, self.stderr = out, code, err


class Runner:
    """Answers the read-only commands the survey uses from fixed JSON."""
    def __init__(self, disks=(), pvs=(), lvs=(), root_source="/dev/mapper/pve-root", fail=(), root_vg_uuid="uuid-a"):
        self.disks, self.pvs, self.lvs, self.root_source, self.fail, self.calls = list(disks), list(pvs), list(lvs), root_source, set(fail), []
        self.root_vg_uuid = root_vg_uuid

    def run(self, argv, timeout=15):
        self.calls.append(list(argv))
        name = argv[0]
        if name in self.fail:
            return Proc(code=1, err=f"{name} failed")
        if name == "lsblk":
            return Proc(json.dumps({"blockdevices": self.disks}))
        if name == "pvs":
            return Proc(json.dumps({"report": [{"pv": self.pvs}]}))
        if name == "lvs" and "--noheadings" in argv:
            return Proc(self.root_vg_uuid + "\n")
        if name == "lvs":
            return Proc(json.dumps({"report": [{"lv": self.lvs}]}))
        if name == "findmnt":
            return Proc(self.root_source + "\n")
        return Proc()


def disk(path, serial, ptuuid=None, children=()):
    return {"name": path, "type": "disk", "serial": serial, "size": 512110190592, "ptuuid": ptuuid, "children": list(children)}


def part(path, label=None, fstype=None):
    return {"name": path, "type": "part", "label": label, "fstype": fstype}


def test_exactly_one_returns_the_only_item_and_lists_everything_when_there_are_none_or_several():
    assert card.exactly_one(["a"], "drive") == "a"
    with pytest.raises(card.CardinalityError, match="no drive") as none:
        card.exactly_one([], "drive")
    assert none.value.found == []
    with pytest.raises(card.CardinalityError, match=r"2 drives.*b.*c") as many:
        card.exactly_one(["b", "c"], "drive")
    assert many.value.found == ["b", "c"]
    assert card.at_most_one([], "drive") is None and card.at_most_one(["a"], "drive") == "a"
    with pytest.raises(card.CardinalityError):
        card.at_most_one(["a", "b"], "drive")


def test_duplicates_names_every_key_that_occurs_more_than_once_with_all_its_items():
    got = card.duplicates([("pve", 1), ("data", 2), ("pve", 3)], key=lambda i: i[0])
    assert got == {"pve": [("pve", 1), ("pve", 3)]}
    assert card.duplicates([("a", 1), ("b", 2)], key=lambda i: i[0]) == {}


def two_proxmox_drives():
    a = disk("/dev/sda", "AAAA1111BBBB2222", children=[part("/dev/sda3", fstype="LVM2_member")])
    b = disk("/dev/sdb", "CCCC3333DDDD4444", children=[part("/dev/sdb3", fstype="LVM2_member")])
    pvs = [{"pv_name": "/dev/sda3", "vg_name": "pve", "vg_uuid": "uuid-a"}, {"pv_name": "/dev/sdb3", "vg_name": "pve", "vg_uuid": "uuid-b"}]
    lvs = [{"lv_name": "root", "vg_name": "pve", "vg_uuid": "uuid-a"}, {"lv_name": "data", "vg_name": "pve", "vg_uuid": "uuid-a"},
           {"lv_name": "root", "vg_name": "pve", "vg_uuid": "uuid-b"}, {"lv_name": "swap", "vg_name": "pve", "vg_uuid": "uuid-b"}]
    return Runner([a, b], pvs, lvs)


def test_the_survey_finds_two_proxmox_installs_and_the_volume_group_name_they_share():
    s = card.survey(two_proxmox_drives())
    assert [d.serial for d in s.proxmox_installs()] == ["AAAA1111BBBB2222", "CCCC3333DDDD4444"]
    assert list(s.duplicate_vg_names()) == ["pve"] and len(s.vgs_named("pve")) == 2
    report = s.assess()
    assert report["proxmox_installs"] == 2 and report["duplicate_vg_names"] == ["pve"] and report["ambiguous"] is True
    assert any("more than one Proxmox" in p for p in report["problems"]) and any("'pve'" in p for p in report["problems"])


def test_one_proxmox_drive_with_one_volume_group_is_unambiguous():
    runner = two_proxmox_drives()
    runner.disks, runner.pvs, runner.lvs = runner.disks[:1], runner.pvs[:1], runner.lvs[:2]
    report = card.survey(runner).assess()
    assert report["proxmox_installs"] == 1 and report["duplicate_vg_names"] == [] and report["ambiguous"] is False and report["problems"] == []


def test_a_serial_that_is_on_two_disks_or_none_is_not_resolved_by_picking_one():
    s = card.survey(Runner([disk("/dev/sda", "SAMESERIAL000001"), disk("/dev/sdc", "SAMESERIAL000001")]))
    with pytest.raises(card.CardinalityError, match="SAMESERIAL000001"):
        s.disk_for_serial("SAMESERIAL000001")
    with pytest.raises(card.CardinalityError, match="no drive"):
        s.disk_for_serial("NOTATTACHED00001")
    assert card.survey(Runner([disk("/dev/sda", "ONLYONE000000001")])).disk_for_serial("ONLYONE000000001").path == "/dev/sda"


def test_baseline_drives_are_the_ones_carrying_baseline_volume_labels():
    d = disk("/dev/sdb", "BASELINEDRIVE0001", children=[part("/dev/sdb1", label="USER_ADMIN"), part("/dev/sdb2", label="INSTALLER_CACHE")])
    other = disk("/dev/sdc", "PLAINDRIVE0000001", children=[part("/dev/sdc1", label="Photos")])
    s = card.survey(Runner([d, other]))
    assert [x.serial for x in s.baseline_drives()] == ["BASELINEDRIVE0001"]


def test_a_failing_or_unreadable_inventory_is_an_error_never_an_empty_answer():
    with pytest.raises(card.CardinalityError, match="lsblk"):
        card.survey(Runner(fail={"lsblk"}))
    with pytest.raises(card.CardinalityError, match="pvs"):
        card.survey(Runner([disk("/dev/sda", "AAAA1111BBBB2222")], fail={"pvs"}))


def test_the_hosts_own_volume_group_is_the_one_its_root_lives_in_and_two_with_that_name_are_refused():
    runner = Runner(pvs=[{"pv_name": "/dev/sda3", "vg_name": "baseline_abc", "vg_uuid": "uuid-a"}], lvs=[{"lv_name": "root", "vg_name": "baseline_abc", "vg_uuid": "uuid-a"}],
                    root_source="/dev/mapper/baseline_abc-root")
    assert card.host_vg(runner) == {"name": "baseline_abc", "uuid": "uuid-a", "name_shared": False}
    clash = two_proxmox_drives()
    assert card.host_vg(clash) == {"name": "pve", "uuid": "uuid-a", "name_shared": True}   # the running root's own UUID tells them apart
    with pytest.raises(card.CardinalityError, match="2 volume groups are named 'pve'"):
        card.host_vg(clash, require_unique_name=True)                                    # a caller that can only use the name must not guess
    lost = two_proxmox_drives()
    lost.root_vg_uuid = "uuid-not-listed"
    with pytest.raises(card.CardinalityError, match="2 volume groups are named 'pve'"):
        card.host_vg(lost)
    not_lvm = Runner(root_source="/dev/nvme0n1p2")
    assert card.host_vg(not_lvm) is None                                              # a root outside LVM has no volume group to resolve
