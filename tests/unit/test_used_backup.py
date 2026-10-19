"""The rule that an image larger than the data it holds is a failure, not a backup (operator 2026-10-19). The real-tool proof is
tests/integration/test_used_backup_real.py (unit tests may not run disk tools)."""
import pytest

import used_backup as ub

MIB = 2 ** 20


def test_an_image_larger_than_the_data_it_holds_is_a_failure_not_a_backup():
    assert ub.accept_size(used_bytes=10 * MIB, image_bytes=11 * MIB) is True
    with pytest.raises(ub.UsedBackupError, match="empty space"):
        ub.accept_size(used_bytes=10 * MIB, image_bytes=300 * MIB)


def test_partclone_output_is_read_for_the_used_and_device_sizes():
    text = "Device size:   67.1 MB = 16384 Blocks\nSpace in use:  12.6 MB = 3074 Blocks\nFree Space:    54.5 MB = 13310 Blocks\nBlock size:   4096 Byte\n"
    assert ub._info(text) == {"used_bytes": 3074 * 4096, "device_bytes": 16384 * 4096, "block_size": 4096}
    with pytest.raises(ub.UsedBackupError):
        ub._info("nothing useful")


def test_every_supported_filesystem_has_a_partclone_tool_and_nothing_falls_back_to_a_raw_copy():
    assert set(ub.FS_TOOLS) >= {"ext4", "vfat"} and all(t.startswith("partclone.") for t in ub.FS_TOOLS.values())
