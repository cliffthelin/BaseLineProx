import sqlite3
import settings_web as sw


def test_login_survives_store_reopen_without_storing_bearer_token(tmp_path):
    path=tmp_path/'sessions.sqlite';key=b'x'*32
    first=sw.SessionStore(path=path,mac_key=key)
    session=first.create('test-user',100,role='operator')
    reopened=sw.SessionStore(path=path,mac_key=key)
    assert reopened.get(session.token,101).role=='operator'
    assert session.token.encode() not in path.read_bytes()
    assert path.stat().st_mode & 0o777==0o600
    assert reopened.get(session.token,100+session.ttl_s+1) is None


def test_role_update_and_logout_are_durable_and_modified_rows_are_refused(tmp_path):
    path=tmp_path/'sessions.sqlite';key=b'x'*32
    store=sw.SessionStore(path=path,mac_key=key)
    session=store.create('test-user',100)
    session.role='operator';store.persist(session)
    assert sw.SessionStore(path=path,mac_key=key).get(session.token,101).role=='operator'
    with sqlite3.connect(path) as db:db.execute("UPDATE sessions SET document=replace(document,'operator','admin')")
    assert sw.SessionStore(path=path,mac_key=key).get(session.token,101) is None
    another=store.create('test-user',100);store.revoke(another.token)
    assert sw.SessionStore(path=path,mac_key=key).get(another.token,101) is None


def test_restart_accepts_session_after_server_reopen_without_weakening_gate(tmp_path):
    import baseline_web as bw
    from test_baseline_web import _RealServerCase,_base_deps
    from test_host_restart import runner_for
    path=tmp_path/'sessions.sqlite';key=b'x'*32
    old=sw.SessionStore(path=path,mac_key=key)
    session=old.create('test-user',100)
    runner=runner_for()
    case=_RealServerCase(_base_deps(sessions=sw.SessionStore(path=path,mac_key=key),clock=lambda:101,runner=runner))
    try:
        case.token=session.token
        status,result=case.post_json('/host/restart',{})
        assert status==200 and result['outcome']=='confirmation_requested'
        old.revoke(session.token)
        runner.calls.clear()
        status,result=case.post_json('/host/restart',{})
        assert status==401 and not runner.calls
        assert "response.status === 401" in bw.render_nav('/settings')
        assert "link.href = '/login'" in bw.render_nav('/settings')
    finally:case.close()


def test_session_requests_close_their_sqlite_connections(tmp_path,monkeypatch):
    import pytest
    native_connect=sqlite3.connect;connections=[]
    def track(*args,**kwargs):
        connection=native_connect(*args,**kwargs);connections.append(connection);return connection
    monkeypatch.setattr(sqlite3,'connect',track)
    store=sw.SessionStore(path=tmp_path/'sessions.sqlite',mac_key=b'x'*32)
    session=store.create('test-user',100)
    assert store.get(session.token,101)
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError,match='closed'):
            connection.execute('SELECT 1')
