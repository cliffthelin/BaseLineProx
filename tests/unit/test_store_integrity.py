"""Row 52: the stores that hold password hashes are signed with a root-only key, verified on every read, and fail
closed: a row someone edited or planted is ignored (never trusted), an alert is raised, and first-run account
creation does not reopen because rows were tampered with."""
import json
import sqlite3

import pytest

import operator_accounts as oa
import settings_web as sw

KEY = b"k" * 32


def make(tmp_path, alerts=None, key=KEY, marker=True):
    return sw.LocalAppStore(tmp_path / "store.db", mac_key=key,
                            mac_marker=(tmp_path / "state" / "store.initialized") if marker else None,
                            on_tamper=(alerts.append if alerts is not None else None))


def raw(tmp_path, sql, args=()):
    conn = sqlite3.connect(str(tmp_path / "store.db"))
    conn.execute(sql, args)
    conn.commit()
    conn.close()


def test_normal_use_round_trips_and_nothing_is_flagged(tmp_path):
    alerts = []
    s = make(tmp_path, alerts)
    s.add_user("cane", "$6$salt$hash")
    s.set_machine_passphrase_hash("$6$s$p")
    s.set_elevation_hash("$6$s$e")
    again = make(tmp_path, alerts)
    assert again.get_user_hash("cane") == "$6$salt$hash"
    assert again.get_machine_passphrase_hash() == "$6$s$p" and again.get_elevation_hash() == "$6$s$e"
    assert alerts == []


def test_a_swapped_user_hash_is_ignored_and_alerted(tmp_path):
    alerts = []
    s = make(tmp_path, alerts)
    s.add_user("cane", "$6$salt$real")
    raw(tmp_path, "UPDATE kv SET value=? WHERE namespace='users' AND key='cane'", (json.dumps("$6$salt$attacker"),))
    assert make(tmp_path, alerts).get_user_hash("cane") is None
    assert alerts and alerts[0]["namespace"] == "users"


def test_a_planted_user_with_no_signature_is_ignored(tmp_path):
    alerts = []
    make(tmp_path, alerts).add_user("cane", "$6$salt$real")
    raw(tmp_path, "INSERT INTO kv (namespace,key,value) VALUES ('users','mallory',?)", (json.dumps("$6$s$h"),))
    s = make(tmp_path, alerts)
    assert s.get_user_hash("mallory") is None and s.get_user_hash("cane") == "$6$salt$real"
    assert alerts


def test_a_swapped_machine_passphrase_or_elevation_hash_is_ignored(tmp_path):
    alerts = []
    s = make(tmp_path, alerts)
    s.set_machine_passphrase_hash("$6$s$p")
    s.set_elevation_hash("$6$s$e")
    raw(tmp_path, "UPDATE kv SET value=? WHERE namespace='auth'", (json.dumps("$6$x$evil"),))
    again = make(tmp_path, alerts)
    assert again.get_machine_passphrase_hash() is None and again.get_elevation_hash() is None


def test_a_row_cannot_be_moved_to_another_key_with_its_signature(tmp_path):
    alerts = []
    s = make(tmp_path, alerts)
    s.add_user("cane", "$6$salt$real")
    s.add_user("other", "$6$salt$other")
    conn = sqlite3.connect(str(tmp_path / "store.db"))
    mac = conn.execute("SELECT mac FROM kv_mac WHERE namespace='users' AND key='cane'").fetchone()[0]
    conn.execute("INSERT INTO kv (namespace,key,value) VALUES ('users','mallory',?)", (json.dumps("$6$salt$real"),))
    conn.execute("INSERT INTO kv_mac (namespace,key,mac) VALUES ('users','mallory',?)", (mac,))
    conn.commit()
    conn.close()
    assert make(tmp_path, alerts).get_user_hash("mallory") is None


def test_tampering_does_not_reopen_first_run_account_creation(tmp_path):
    alerts = []
    s = make(tmp_path, alerts)
    s.add_user("cane", "$6$salt$real")
    raw(tmp_path, "UPDATE kv SET value=? WHERE namespace='users'", (json.dumps("$6$x$evil"),))
    assert make(tmp_path, alerts).has_user_data() is True


def test_a_replaced_database_is_not_adopted_once_the_store_has_been_initialized(tmp_path):
    alerts = []
    make(tmp_path, alerts).add_user("cane", "$6$salt$real")
    (tmp_path / "store.db").unlink()
    for ext in ("-wal", "-shm"):
        (tmp_path / f"store.db{ext}").unlink(missing_ok=True)
    attacker = sw.LocalAppStore(tmp_path / "store.db")            # an unsigned database with the attacker's own user
    attacker.add_user("cane", "$6$salt$attacker")
    attacker._conn.close()
    assert make(tmp_path, alerts).get_user_hash("cane") is None


def test_an_existing_unsigned_store_is_adopted_once_then_enforced(tmp_path):
    plain = sw.LocalAppStore(tmp_path / "store.db")
    plain.add_user("cane", "$6$salt$real")
    plain._conn.close()
    alerts = []
    adopted = make(tmp_path, alerts)
    assert adopted.get_user_hash("cane") == "$6$salt$real" and alerts == []
    raw(tmp_path, "UPDATE kv SET value=? WHERE namespace='users'", (json.dumps("$6$x$evil"),))
    assert make(tmp_path, alerts).get_user_hash("cane") is None


def test_settings_that_are_not_secret_are_not_signed_or_blocked(tmp_path):
    s = make(tmp_path)
    s.update_section("network", {"x": 1})
    raw(tmp_path, "UPDATE kv SET value=? WHERE namespace='settings' AND key='network'", (json.dumps({"x": 2}),))
    assert make(tmp_path).settings()["network"] == {"x": 2}


def test_a_different_key_does_not_verify(tmp_path):
    make(tmp_path).add_user("cane", "$6$salt$real")
    assert make(tmp_path, key=b"z" * 32).get_user_hash("cane") is None


# -- operator accounts file ----------------------------------------------------------

def accounts(tmp_path, alerts=None):
    return oa.OperatorAccounts(tmp_path / "ops.json", is_system_user=lambda n: False, mac_key=KEY,
                               on_tamper=(alerts.append if alerts is not None else None))


def test_operator_accounts_are_signed_and_a_hand_edit_is_ignored(tmp_path):
    alerts = []
    accounts(tmp_path).add("claude", "a long operator password", "bot:repair")
    data = json.loads((tmp_path / "ops.json").read_text())
    data["accounts"]["claude"]["role"] = "operator"
    (tmp_path / "ops.json").write_text(json.dumps(data))
    s = accounts(tmp_path, alerts)
    assert s.names() == [] and s.verify("claude", "a long operator password") is False and alerts


def test_a_planted_operator_account_cannot_log_in(tmp_path):
    good = accounts(tmp_path)
    good.add("claude", "a long operator password")
    data = json.loads((tmp_path / "ops.json").read_text())
    data["accounts"]["mallory"] = data["accounts"]["claude"]
    (tmp_path / "ops.json").write_text(json.dumps(data))
    assert accounts(tmp_path).verify("mallory", "a long operator password") is False


def test_an_unsigned_operator_file_is_refused_when_a_key_is_configured(tmp_path):
    plain = oa.OperatorAccounts(tmp_path / "ops.json", is_system_user=lambda n: False)
    plain.add("claude", "a long operator password")
    assert accounts(tmp_path).verify("claude", "a long operator password") is False


def test_operator_accounts_round_trip_with_a_key(tmp_path):
    accounts(tmp_path).add("claude", "a long operator password")
    s = accounts(tmp_path)
    assert s.verify("claude", "a long operator password") and s.names() == ["claude"]
    assert s.remove("claude") and accounts(tmp_path).names() == []


def test_the_real_server_signs_its_credential_stores_and_shows_an_alert(tmp_path):
    import baseline_web as bw
    server = bw.build_real_server(host="127.0.0.1", port=0, data_path=tmp_path / "store.db", state_dir=tmp_path / "state")
    try:
        deps = server.deps
        assert deps["store"]._mac_key is not None and deps["operator_accounts"]._mac_key is not None
        assert deps["store"]._mac_key != deps["operator_accounts"]._mac_key != deps["web_gate"]._key
        deps["store"].add_user("cane", "$6$salt$real")
        raw(tmp_path, "UPDATE kv SET value=? WHERE namespace='users'", (json.dumps("$6$x$evil"),))
        deps["store"]._reported.clear()
        assert deps["store"].get_user_hash("cane") is None
        assert deps["tamper_alerts"] and deps["tamper_alerts"][0]["namespace"] == "users"
        log = (tmp_path / "state" / "audit" / "web-actions.jsonl").read_text()
        assert "integrity_failure" in log and "evil" not in log
    finally:
        server.server_close()


def test_the_operations_page_shows_integrity_alerts():
    import operations as ops
    import operations_page as op
    page = op.render_operations_page(ops.OPERATIONS, [], [{"namespace": "users", "detail": "a row failed"}]).decode()
    assert "Integrity alert" in page and "a row failed" in page
