"""Real-file transaction checks; no device commands or fake runners."""
import json

import pytest

import host_layout as layout

SERIAL = "SYNTHDRIVEB00002"


def test_retry_after_live_rename_keeps_original_boot_reference(tmp_path):
    pending = tmp_path / "rename.json"
    first = layout.prepare_group_rename(pending, serial=SERIAL, vg="pve", vg_uuid="uuid-401")
    assert json.loads(pending.read_text()) == first
    retry = layout.prepare_group_rename(pending, serial=SERIAL, vg=first["new"], vg_uuid="uuid-401")
    assert retry == first and retry["old"] == "pve"


def test_pending_repair_cannot_be_reused_for_another_drive(tmp_path):
    pending = tmp_path / "rename.json"
    layout.prepare_group_rename(pending, serial=SERIAL, vg="pve", vg_uuid="uuid-401")
    before = pending.read_bytes()
    with pytest.raises(layout.LayoutError, match="identity"):
        layout.prepare_group_rename(pending, serial=SERIAL, vg="pve", vg_uuid="foreign")
    assert pending.read_bytes() == before


def test_completed_name_needs_no_new_transaction(tmp_path):
    pending = tmp_path / "rename.json"
    assert layout.prepare_group_rename(pending, serial=SERIAL,
        vg=layout.volume_group_name_for(SERIAL), vg_uuid="uuid-401") is None
    assert not pending.exists()


def test_symlink_transaction_cannot_redirect_root_write(tmp_path):
    outside = tmp_path / "outside"
    outside.write_text("preserve")
    pending = tmp_path / "rename.json"
    pending.symlink_to(outside)
    with pytest.raises(layout.LayoutError, match="symlink"):
        layout.prepare_group_rename(pending, serial=SERIAL, vg="pve", vg_uuid="uuid-401")
    assert outside.read_text() == "preserve"
