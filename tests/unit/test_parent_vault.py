import subprocess

import pytest

import data_vault as dv
import parent_vault as pv
from repair import RealRunner

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"


def make_volume(tmp_path, name, text):
    v = tmp_path / name
    (v / "docs").mkdir(parents=True)
    (v / "docs" / "f.txt").write_text(text)
    dv.snapshot(RealRunner(), v, "USER_PERSONAL", message="m")
    return v


def test_combination_id_is_order_independent_and_matches_the_twin_pair_id():
    import identifiers
    import twin_sync
    lane = "11111111-2222-4333-8444-555555555555"
    x, y = identifiers.host_id(lane, "SYNTHHOST0000001"), identifiers.host_id(lane, "SYNTHTWIN0000001")
    assert pv.combination_for([x, y]) == pv.combination_for([y, x]) == twin_sync.pair_id_for(x, y)
    assert pv.combination_for([A]) != pv.combination_for([A, B])


def test_each_drive_of_a_pair_gets_its_own_branch_in_one_repository(tmp_path):
    root, r = tmp_path / "parent", RealRunner()
    va, vb = make_volume(tmp_path, "a", "from a"), make_volume(tmp_path, "b", "from b")
    one = pv.push(r, va, root, child_ids=[A, B], this_child=A, role="USER_PERSONAL")
    two = pv.push(r, vb, root, child_ids=[A, B], this_child=B, role="USER_PERSONAL")
    assert one["combination"] == two["combination"] and one["branch"] != two["branch"] and one["commit"] != two["commit"]


def test_restore_returns_exactly_what_was_pushed(tmp_path):
    root, r = tmp_path / "parent", RealRunner()
    v = make_volume(tmp_path, "a", "keep me")
    info = pv.push(r, v, root, child_ids=[A], this_child=A, role="USER_PERSONAL")
    out = pv.restore(r, root, combination=info["combination"], child=A, role="USER_PERSONAL", destination=tmp_path / "back")
    assert (tmp_path / "back" / "docs" / "f.txt").read_text() == "keep me"
    with pytest.raises(pv.ParentVaultError):
        pv.restore(r, root, combination=info["combination"], child=A, role="USER_PERSONAL", destination=out)


def test_pushing_an_unchanged_volume_again_writes_no_new_objects(tmp_path):
    root, r = tmp_path / "parent", RealRunner()
    v = make_volume(tmp_path, "a", "same")
    first = pv.push(r, v, root, child_ids=[A], this_child=A, role="USER_PERSONAL")
    bare = pv.repo_path(root, first["combination"], "USER_PERSONAL")
    count = lambda: subprocess.run(["git", "--git-dir", str(bare), "count-objects"], capture_output=True, text=True).stdout
    before = count()
    assert pv.push(r, v, root, child_ids=[A], this_child=A, role="USER_PERSONAL")["commit"] == first["commit"] and count() == before


def test_a_drive_outside_the_combination_is_refused(tmp_path):
    v = make_volume(tmp_path, "a", "x")
    with pytest.raises(pv.ParentVaultError):
        pv.push(RealRunner(), v, tmp_path / "p", child_ids=[A], this_child=B, role="USER_PERSONAL")


def test_listing_names_drives_by_child_uuid_only(tmp_path):
    root, r = tmp_path / "parent", RealRunner()
    pv.push(r, make_volume(tmp_path, "a", "x"), root, child_ids=[A, B], this_child=A, role="USER_PERSONAL")
    [entry] = pv.listing(root)
    assert entry["drives"] == sorted([A, B]) and entry["roles"] == ["USER_PERSONAL"]
