"""Production refusal paths; no devices opened or injected command results."""
import pytest

import installed_drive_update as update


def test_pc601_update_lane_refuses_pc401_before_discovery():
    with pytest.raises(update.UpdateError, match="other installer lane"):
        update.discover_path("MD89N41071210AP4E")


def test_pc601_updater_refuses_pc401_even_with_an_invalid_bundle(tmp_path):
    with pytest.raises(update.UpdateError, match="other installer lane"):
        update.update(None, serial="MD89N41071210AP4E", input_bundle=tmp_path / "missing",
                      recovery_folder=tmp_path / "missing-recovery", root=tmp_path / "root")
