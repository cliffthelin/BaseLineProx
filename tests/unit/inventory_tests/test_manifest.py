from inventory import manifest as manifest_mod
from inventory.redact import Redactor
from inventory.schema import to_json

from .fake_runner import FakeRunner


def _fixed_clock():
    return "2026-01-01T00:00:00Z"


def test_fixed_key_and_clock_produce_byte_identical_output():
    """Correction #6: production runs use a fresh ephemeral HMAC key, so
    two independent production-style runs cannot be byte-identical - but
    with the key and clock both injected and fixed, two runs against
    equivalent input MUST be byte-identical."""
    r1, r2 = FakeRunner(), FakeRunner()
    m1 = manifest_mod.collect_all(
        r1, source="current-drive", host_label="test",
        redactor=Redactor(key=b"fixed-key"), clock=_fixed_clock,
    )
    m2 = manifest_mod.collect_all(
        r2, source="current-drive", host_label="test",
        redactor=Redactor(key=b"fixed-key"), clock=_fixed_clock,
    )
    assert to_json(m1) == to_json(m2)


def test_default_production_style_calls_use_a_different_key_each_time():
    r1, r2 = FakeRunner(), FakeRunner()
    r1.dirs["/etc/pve/nodes/samehost/qemu-server"] = []
    r1.dirs["/etc/pve/nodes/samehost/lxc"] = []
    r2.dirs["/etc/pve/nodes/samehost/qemu-server"] = []
    r2.dirs["/etc/pve/nodes/samehost/lxc"] = []

    # No redactor passed - collect_all makes its own fresh, ephemeral
    # Redactor() each call, matching real production behavior.
    m1 = manifest_mod.collect_all(r1, source="current-drive", host_label="test",
                                   clock=_fixed_clock, node_names=["samehost"])
    m2 = manifest_mod.collect_all(r2, source="current-drive", host_label="test",
                                   clock=_fixed_clock, node_names=["samehost"])

    token1 = next(iter(m1["categories"]["proxmox"]["nodes"]))
    token2 = next(iter(m2["categories"]["proxmox"]["nodes"]))
    assert token1 != token2


def test_same_key_within_one_run_produces_stable_repeated_tokens():
    r = FakeRunner()
    r.dirs["/etc/pve/nodes/samehost/qemu-server"] = ["100.conf"]
    r.files["/etc/pve/nodes/samehost/qemu-server/100.conf"] = "cores: 2\n"
    r.dirs["/etc/pve/nodes/samehost/lxc"] = []
    r.binaries["pvesm"] = "/usr/sbin/pvesm"

    redactor = Redactor(key=b"fixed-key")
    manifest = manifest_mod.collect_all(
        r, source="current-drive", host_label="test",
        redactor=redactor, clock=_fixed_clock, node_names=["samehost"],
    )
    node_token = next(iter(manifest["categories"]["proxmox"]["nodes"]))
    # Same host name, tokenized independently outside the manifest build,
    # must match the token that ended up in the manifest - proving the
    # same key produces the same token for the same value every time.
    assert node_token == redactor.tokenize("samehost", "host")


def test_write_manifest_refuses_forbidden_output_path(tmp_path):
    r = FakeRunner()
    manifest = manifest_mod.collect_all(r, source="current-drive", host_label="test", clock=_fixed_clock)
    from inventory.pathsafety import OutputPathError
    import pytest
    with pytest.raises(OutputPathError):
        manifest_mod.write_manifest(manifest, "/etc/pve/out.json", repo_root=str(tmp_path / "repo"))


def test_write_manifest_writes_valid_json_to_disk(tmp_path):
    r = FakeRunner()
    manifest = manifest_mod.collect_all(r, source="current-drive", host_label="test", clock=_fixed_clock)
    out_path = tmp_path / "manifest.json"
    resolved = manifest_mod.write_manifest(manifest, str(out_path), repo_root=str(tmp_path / "repo"))
    import json
    with open(resolved) as f:
        loaded = json.load(f)
    assert loaded["schema_version"] == 2
    assert loaded["source"] == "current-drive"
