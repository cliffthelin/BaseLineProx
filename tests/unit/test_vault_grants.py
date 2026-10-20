"""Which secrets each place may receive (a virtual machine, Kasm, an application), and delivery into a running guest: the value goes through stdin into the guest's RAM
(/run/baseline-vault), never into argv, a log, a seed or the guest's disk."""
import json
import pytest

import vault_grants as vg


def test_grant_and_revoke_are_recorded_by_target(tmp_path):
    path = tmp_path / "grants.json"
    vg.grant(path, "vm:debian-1", "GOOGLE_LOGIN")
    vg.grant(path, "vm:debian-1", "CLAUDE_CODE_OAUTH_TOKEN")
    vg.grant(path, "kasm", "GOOGLE_LOGIN")
    assert vg.granted(path, "vm:debian-1") == ["CLAUDE_CODE_OAUTH_TOKEN", "GOOGLE_LOGIN"]
    vg.revoke(path, "vm:debian-1", "GOOGLE_LOGIN")
    assert vg.granted(path, "vm:debian-1") == ["CLAUDE_CODE_OAUTH_TOKEN"] and vg.granted(path, "kasm") == ["GOOGLE_LOGIN"]


def test_bad_targets_and_names_are_refused(tmp_path):
    path = tmp_path / "grants.json"
    for target in ("", "vm:", "vm:a b", "x:y", "vm:../x"):
        with pytest.raises(vg.GrantError):
            vg.grant(path, target, "GOOGLE_LOGIN")
    with pytest.raises(vg.GrantError):
        vg.grant(path, "kasm", "lower")


def test_a_missing_or_damaged_file_means_no_grants(tmp_path):
    path = tmp_path / "grants.json"
    assert vg.granted(path, "kasm") == []
    path.write_text("not json")
    assert vg.granted(path, "kasm") == []


def test_an_unchanged_grant_does_not_rewrite_the_file(tmp_path):
    path = tmp_path / "grants.json"
    vg.grant(path, "kasm", "GOOGLE_LOGIN")
    before = path.stat().st_mtime_ns
    vg.grant(path, "kasm", "GOOGLE_LOGIN")
    assert path.stat().st_mtime_ns == before


def test_delivery_sends_the_value_on_stdin_only(tmp_path):
    path = tmp_path / "grants.json"
    vg.grant(path, "vm:d", "GOOGLE_LOGIN")
    sent = []
    def push(argv, data):
        sent.append((argv, data))
    report = vg.deliver(path, "vm:d", lambda name: "s3cret-value", push)
    assert report == {"delivered": ["GOOGLE_LOGIN"], "skipped": {}}
    argv, data = sent[0]
    assert data == b"s3cret-value" and "s3cret-value" not in " ".join(argv)
    assert "/run/baseline-vault" in " ".join(argv) and "GOOGLE_LOGIN" in " ".join(argv)


def test_guest_secret_directory_is_owned_by_the_recipient_and_private(tmp_path):
    path = tmp_path / "grants.json"
    vg.grant(path, "vm:d", "GOOGLE_LOGIN")
    sent = []
    vg.deliver(path, "vm:d", lambda _name: "synthetic-secret", lambda argv, data: sent.append((argv, data)), owner_uid=1100)
    script = " ".join(sent[0][0])
    assert "1100" in script and "-m 0700" in script and "chmod 0600" in script
    assert "BASELINE_VAULT_DIR" in next(f["content"] for f in vg.GUEST_FILES if f["path"].endswith("baseline-vault.sh"))


def test_a_sealed_or_missing_secret_is_skipped_with_a_reason_not_a_crash(tmp_path):
    path = tmp_path / "grants.json"
    vg.grant(path, "kasm", "GOOGLE_LOGIN"); vg.grant(path, "kasm", "OTHER_SECRET")
    def read(name):
        if name == "GOOGLE_LOGIN":
            raise vg.Unavailable("the vault is locked")
        return None
    report = vg.deliver(path, "kasm", read, lambda argv, data: None)
    assert report["delivered"] == [] and set(report["skipped"]) == {"GOOGLE_LOGIN", "OTHER_SECRET"}


def test_a_guest_that_cannot_be_reached_is_reported_per_secret(tmp_path):
    path = tmp_path / "grants.json"
    vg.grant(path, "kasm", "GOOGLE_LOGIN")
    def push(argv, data):
        raise OSError("the guest agent is not running")
    report = vg.deliver(path, "kasm", lambda n: "abcdefgh", push)
    assert report["delivered"] == [] and "agent" in report["skipped"]["GOOGLE_LOGIN"]
    assert "abcdefgh" not in json.dumps(report)


def test_every_guest_seed_carries_the_helpers():
    import prebuilt_environment as pe
    config = json.loads(pe.cloud_config("debian", owner="cliff", initialize_home=True, hostname="d1").split("\n", 1)[1])
    paths = {f["path"] for f in config["write_files"]}
    assert {"/etc/profile.d/baseline-vault.sh", "/usr/local/bin/baseline-vault"} <= paths


def test_the_helper_refuses_a_path_instead_of_a_name():
    script = next(f for f in vg.GUEST_FILES if f["path"].endswith("baseline-vault"))["content"]
    assert '*/*' in script and "/run/baseline-vault" in script


def test_the_guest_agent_reaches_ready_made_systems_made_with_a_seed():
    import proxmox_vm_host as pvh
    assert pvh.guest_agent_recipe({"recipe": "prebuilt-debian", "seed": True})
    assert pvh.guest_agent_recipe({"recipe": "ubuntu-desktop"})
    assert not pvh.guest_agent_recipe({"recipe": "prebuilt-fydeos"})            # no seed, so no guest agent was turned on
    assert not pvh.guest_agent_recipe({"recipe": "iso"}) and not pvh.guest_agent_recipe({})
