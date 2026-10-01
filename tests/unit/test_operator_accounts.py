"""Operator accounts: created in the web application by the owner (root password required), stored only as salted
one-way hashes, limited to the Operations role."""
import json
import stat

import pytest

import operator_accounts as oa


def store(tmp_path, **kw):
    return oa.OperatorAccounts(tmp_path / "operators.json", is_system_user=kw.pop("is_system_user", lambda n: False), **kw)


PW = "correct horse battery"


def test_add_then_verify(tmp_path):
    s = store(tmp_path)
    s.add("claude", PW)
    assert s.verify("claude", PW) is True
    assert s.verify("claude", PW + "x") is False
    assert s.verify("nobody", PW) is False
    assert s.names() == ["claude"]


def test_the_password_is_never_stored_only_a_salted_one_way_hash(tmp_path):
    s = store(tmp_path)
    s.add("claude", PW)
    s.add("other", PW)
    raw = (tmp_path / "operators.json").read_text()
    assert PW not in raw
    records = json.loads(raw)["accounts"]
    assert records["claude"]["hash"] != records["other"]["hash"]       # per-account salt
    assert stat.S_IMODE((tmp_path / "operators.json").stat().st_mode) == 0o600


@pytest.mark.parametrize("name", ["", "ab", "Root", "root", "a b", "../x", "x" * 40, "1abc", "adm;in", "a\nb"])
def test_bad_or_reserved_names_are_refused(tmp_path, name):
    with pytest.raises(ValueError):
        store(tmp_path).add(name, PW)


@pytest.mark.parametrize("pw", ["", "short", "x" * 11, None, 12345, "x" * 300])
def test_weak_or_bad_passwords_are_refused(tmp_path, pw):
    with pytest.raises(ValueError):
        store(tmp_path).add("claude", pw)


def test_a_machine_account_name_cannot_be_taken(tmp_path):
    with pytest.raises(ValueError, match="machine account"):
        store(tmp_path, is_system_user=lambda n: n == "cane").add("cane", PW)


def test_an_existing_operator_is_not_overwritten(tmp_path):
    s = store(tmp_path)
    s.add("claude", PW)
    with pytest.raises(ValueError, match="already"):
        s.add("claude", "another long password")
    assert s.verify("claude", PW)


def test_remove_and_the_limit(tmp_path):
    s = store(tmp_path)
    for i in range(oa.MAX_OPERATORS):
        s.add(f"op{i}", PW)
    with pytest.raises(ValueError, match="most"):
        s.add("one-too-many", PW)
    assert s.remove("op0") is True and s.remove("op0") is False
    assert s.verify("op0", PW) is False


def test_a_corrupt_file_means_no_accounts_never_a_crash_or_a_login(tmp_path):
    (tmp_path / "operators.json").write_text("{not json")
    s = store(tmp_path)
    assert s.names() == [] and s.verify("claude", PW) is False


def test_a_tampered_record_does_not_verify(tmp_path):
    s = store(tmp_path)
    s.add("claude", PW)
    data = json.loads((tmp_path / "operators.json").read_text())
    data["accounts"]["claude"]["hash"] = "00"
    (tmp_path / "operators.json").write_text(json.dumps(data))
    assert s.verify("claude", PW) is False
