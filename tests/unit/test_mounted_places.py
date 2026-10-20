"""The list a person chooses a mounted partition from (instead of typing its location). Parses `findmnt -J` output; keeps real block-device
mounts under the connected-drive places only."""
import json

import mounted_places as mp

FINDMNT = json.dumps({"filesystems": [
    {"target": "/", "source": "/dev/mapper/vg-root", "fstype": "ext4", "children": [
        {"target": "/mnt/sdb2", "source": "/dev/sdb2", "fstype": "ext4"},
        {"target": "/run/media/u/BACKUP", "source": "/dev/sdc1", "fstype": "exfat"},
        {"target": "/proc", "source": "proc", "fstype": "proc"},
        {"target": "/mnt/share", "source": "//server/x", "fstype": "cifs"},
        {"target": "/etc/baseline", "source": "/dev/mapper/vg-user[/etc-baseline]", "fstype": "ext4"},
        {"target": "/mnt/bad name", "source": "/dev/sdd1", "fstype": "ext4"}]}]})


def test_only_real_partitions_mounted_in_the_connected_drive_places_are_offered():
    got = mp.parse(FINDMNT)
    assert [(m["target"], m["source"]) for m in got] == [("/mnt/sdb2", "/dev/sdb2"), ("/run/media/u/BACKUP", "/dev/sdc1")]


def test_a_chosen_location_must_be_one_of_the_offered_ones():
    assert mp.choose("/mnt/sdb2", mp.parse(FINDMNT)) == "/mnt/sdb2"
    for bad in ("/mnt/sdb2/../..", "/etc", "", "/mnt/sdb"):
        try:
            mp.choose(bad, mp.parse(FINDMNT))
        except ValueError:
            continue
        raise AssertionError(bad)


def test_bad_input_gives_an_empty_list_not_an_error():
    assert mp.parse("not json") == [] and mp.parse(json.dumps({"filesystems": "x"})) == []
