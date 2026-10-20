"""Carrying ready-made VM bases into the offline cache: only bases that match their manifest and say they hold nothing private."""
import hashlib
import json

import offline_cache as oc


def base(folder, os_id, data=b"disk image bytes", holds=False, sha=None):
    image = folder / f"{os_id}-base.qcow2"
    image.write_bytes(data)
    (folder / f"{os_id}-base.json").write_text(json.dumps({"base": image.name, "sha256": sha or hashlib.sha256(data).hexdigest(), "holds_install_state_or_secrets": holds}))


def test_a_good_base_is_copied_with_its_manifest(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "cache"
    src.mkdir()
    dst.mkdir()
    base(src, "debian")
    got = oc.carry_os_bases(src, dst)
    assert got["carried"] == {"debian": len(b"disk image bytes")} and got["refused"] == {}
    assert (dst / "os-bases" / "debian-base.qcow2").read_bytes() == b"disk image bytes" and (dst / "os-bases" / "debian-base.json").is_file()


def test_a_base_that_may_hold_secrets_or_does_not_match_its_manifest_is_refused_and_reported(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "cache"
    src.mkdir()
    dst.mkdir()
    base(src, "leaky", holds=True)
    base(src, "damaged", sha="0" * 64)
    base(src, "fine")
    (src / "broken-base.json").write_text("{ not json")
    got = oc.carry_os_bases(src, dst)
    assert set(got["carried"]) == {"fine"} and set(got["refused"]) == {"leaky", "damaged", "broken"}
    assert "secrets" in got["refused"]["leaky"] and "checksum" in got["refused"]["damaged"]
    assert not (dst / "os-bases" / "leaky-base.qcow2").exists() and not (dst / "os-bases" / "damaged-base.qcow2").exists()


def test_only_the_named_systems_are_carried_when_asked(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "cache"
    src.mkdir()
    dst.mkdir()
    base(src, "debian")
    base(src, "ubuntu")
    assert set(oc.carry_os_bases(src, dst, only={"ubuntu"})["carried"]) == {"ubuntu"}


def test_with_no_bases_nothing_is_made_and_nothing_fails(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "cache"
    src.mkdir()
    dst.mkdir()
    assert oc.carry_os_bases(src, dst) == {"carried": {}, "refused": {}}
    assert not (dst / "os-bases").exists()
