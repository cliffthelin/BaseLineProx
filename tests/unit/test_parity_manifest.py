import json
from pathlib import Path

import nav_tree
import parity_manifest as pm

GAPS = Path(__file__).with_name("parity_gaps.json")


def test_every_feature_has_a_unique_id_and_a_console_page():
    ids = [f.id for f in pm.FEATURES]
    assert len(ids) == len(set(ids))
    pages = {p.split("?")[0] for p, _ in nav_tree.flatten()}
    assert all(f.route in pages for f in pm.FEATURES)


def test_the_tui_is_fully_inventoried():
    tui = {f.id.split(".")[1] for f in pm.FEATURES if f.source == "tui"}
    assert {"hardware", "network", "sensors", "vms", "chat", "console", "proxmox", "refresh", "status_bar"} <= tui


def test_gaps_match_the_recorded_list_so_none_is_forgotten_or_added_quietly():
    recorded = json.loads(GAPS.read_text())
    assert pm.gaps() == sorted(recorded), "a feature was carried or added: update tests/unit/parity_gaps.json"


def test_nothing_in_the_installer_inventory_is_dropped():
    ids = {f.id for f in pm.FEATURES}
    for required in ("installer.plan", "installer.recipes", "installer.readiness", "installer.cache", "installer.drive_admin",
                     "build.install.wipe_install", "build.install.recovery", "build.cache.offline", "build.iso", "managed.mode"):
        assert required in ids
