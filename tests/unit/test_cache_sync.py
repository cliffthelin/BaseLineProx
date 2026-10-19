import pytest

import cache_sync as cs

GIB = 2 ** 30


def test_no_growth_when_the_difference_already_fits():
    assert cs.growth_needed(5 * GIB, 10 * GIB, 100 * GIB) == 0


def test_growth_covers_the_shortfall_with_filesystem_overhead():
    assert cs.growth_needed(20 * GIB, 10 * GIB, 100 * GIB) == 11          # 10 GiB short, plus ext4's reserved blocks


def test_a_cache_that_cannot_be_given_room_stops_before_anything_is_copied():
    with pytest.raises(cs.CacheSyncError, match="nothing was copied"):
        cs.growth_needed(200 * GIB, 10 * GIB, 100 * GIB)
    with pytest.raises(cs.CacheSyncError):
        cs.growth_needed(20 * GIB, 10 * GIB, 10 * GIB + 512)            # the group's last GiB is never taken


def test_the_copy_is_in_place_by_block_never_whole_file_and_never_deletes():
    flags = " ".join(cs.FLAGS)
    assert "--inplace" in flags and "--no-whole-file" in flags and "--modify-window=-1" in flags and "--delete" not in flags
