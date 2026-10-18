"""The installed-drive updater acts only on this lane's own (or deliberately enrolled) drives, and never on a drive another installer lane stamped. No serial is stored in the code: the lane's drives are
runtime data, and another lane's drive is recognised from the identifier on the drive itself."""
import json

import pytest

import identifiers
import installed_drive_update as update

OTHER_LANE = "11111111-2222-4333-8444-555555555555"      # a lane that is not this one
UNLISTED = "SYNTHUNLISTED0001"                            # a serial in nobody's data


class Lsblk:
    def __init__(self, disks):
        self.disks, self.calls = disks, []

    def run(self, argv, timeout=10):
        self.calls.append(list(argv))
        class P:
            returncode, stderr = 0, ""
        P.stdout = json.dumps({"blockdevices": self.disks})
        return P()


def test_a_serial_that_is_not_this_lanes_or_enrolled_is_refused_before_anything_is_discovered_or_run(tmp_path):
    runner = Lsblk([])
    with pytest.raises(update.UpdateError, match="not one of this installer lane's drives"):
        update.discover_path(UNLISTED, runner=runner)
    assert runner.calls == []
    with pytest.raises(update.UpdateError, match="not one of this installer lane's drives"):
        update.update(None, serial=UNLISTED, input_bundle=tmp_path / "missing", recovery_folder=tmp_path / "r", root=tmp_path / "root")


def test_a_listed_drive_stamped_by_another_lane_is_refused_by_what_is_on_the_drive_itself():
    serial = "SYNTHDRIVEB00002"                                                  # in the test data's list of allowed drives, but the drive says another lane installed it
    stamp = identifiers.host_id(OTHER_LANE, serial)
    runner = Lsblk([{"name": "/dev/sdb", "type": "disk", "serial": serial, "size": 512, "ptuuid": stamp}])
    with pytest.raises(update.UpdateError, match="another installer lane's stamp"):
        update.discover_path(serial, runner=runner)


def test_more_than_one_drive_with_the_serial_is_reported_not_resolved_by_picking_one():
    serial = "SYNTHDRIVEA00001"
    runner = Lsblk([{"name": "/dev/sdb", "type": "disk", "serial": serial, "size": 512}, {"name": "/dev/sdc", "type": "disk", "serial": serial, "size": 512}])
    with pytest.raises(update.UpdateError, match="exactly one attached drive"):
        update.discover_path(serial, runner=runner)
