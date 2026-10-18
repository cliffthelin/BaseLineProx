import pytest

import rebuild_policy as rp

ID = rp.drive_identity("SYNTH-1", 1000)


def policy(**kw):
    return rp.build({"ONE": ID}, **kw)


def test_policy_holds_no_serial():
    assert "SYNTH-1" not in rp.canonical(policy()).decode()


def test_tampered_policy_is_refused(tmp_path):
    p, d = tmp_path / "p.json", tmp_path / "d"
    rp.write(p, d, policy())
    p.write_text(p.read_text().replace("recovery", "anything"))
    with pytest.raises(rp.PolicyError):
        rp.load_verified(p, d)


def test_verified_policy_loads(tmp_path):
    p, d = tmp_path / "p.json", tmp_path / "d"
    rp.write(p, d, policy())
    assert rp.load_verified(p, d)["drives"] == {"ONE": ID}


def cmd(**kw):
    args = dict(target="ONE", serial="SYNTH-1", size_bytes=1000, src="/s", python="py", current_source="s" * 64, approved_source="s" * 64)
    args.update(kw)
    return rp.command_for(policy(), **args)


def test_command_is_the_pinned_template_only():
    assert cmd()[-2:] == ["--confirm-wipe", "SYNTH-1"] and cmd()[2:4] == ["--target", "ONE"]


def test_another_drive_under_the_same_name_is_refused():
    with pytest.raises(rp.PolicyError):
        cmd(serial="SYNTH-2")
    with pytest.raises(rp.PolicyError):
        cmd(size_bytes=999)


def test_changed_source_is_refused():
    with pytest.raises(rp.PolicyError):
        cmd(current_source="x" * 64)


def test_unknown_target_and_bad_ttl_refused():
    with pytest.raises(rp.PolicyError):
        cmd(target="TWO")
    with pytest.raises(rp.PolicyError):
        policy(ttl_hours=rp.MAX_TTL_HOURS + 1)
