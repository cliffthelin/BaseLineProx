"""The real `sfdisk --disk-id` and `blkid -p`, on a temporary GPT image FILE (never a device): what first boot and the host do.

Not a unit test: it runs disk tools, which the unit suite's hardware guard forbids by name. It touches only a file under tmp_path.
Run: python3 -m pytest tests/integration/test_gpt_identity_on_image.py
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "baseline/lib"))
import installer_identity as ii  # noqa: E402

LANE = "4af8c95a-1c9b-437a-a306-c53855d4077f"
PC601 = "FD01N6557110C271B"


def _gpt_image(tmp_path):
    image = tmp_path / "disk.img"
    subprocess.run(["truncate", "-s", "64M", str(image)], check=True)
    subprocess.run(["sfdisk", str(image)], input="label: gpt\n,16M\n", text=True, check=True, capture_output=True)
    return image


def test_the_real_tool_sets_and_reads_back_a_gpt_disk_identifier(tmp_path):
    image = _gpt_image(tmp_path)
    wanted = ii.child_uuid(LANE, PC601)
    assert ii.probe_disk_guid(image) != wanted
    assert ii.ensure_disk_guid(image, wanted) == wanted
    assert ii.probe_disk_guid(image) == wanted
    before = image.read_bytes()
    assert ii.ensure_disk_guid(image, wanted) == wanted                 # already carried: nothing is written again
    assert image.read_bytes() == before


def test_a_device_that_does_not_end_up_with_the_identifier_is_reported(tmp_path):
    blank = tmp_path / "blank.img"
    blank.write_bytes(b"\0" * 4096)                                      # no partition table at all
    with pytest.raises(ii.IdentityError):
        ii.ensure_disk_guid(blank, ii.child_uuid(LANE, PC601))
