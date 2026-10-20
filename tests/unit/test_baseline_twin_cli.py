"""The baseline-twin command: unpaired or detached is a quiet success, pairing needs root, an allowed peer and an explicit yes."""
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

import pytest

import twin_sync as ts

SCRIPT = Path(__file__).parents[2] / "baseline/bin/baseline-twin"


@pytest.fixture
def cli():
    loader = SourceFileLoader("baseline_twin_cli", str(SCRIPT))
    module = module_from_spec(spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


def test_sync_when_not_paired_does_nothing_and_succeeds(cli, monkeypatch, capsys):
    monkeypatch.setattr(ts, "load_twin_config", lambda path=None: None)
    assert cli.main(["sync"]) == 0
    assert "not paired" in capsys.readouterr().out


def test_sync_when_the_twin_is_not_attached_does_nothing_and_succeeds(cli, monkeypatch, capsys):
    monkeypatch.setattr(ts, "load_twin_config", lambda path=None: {"peer": "00000000-0000-0000-0000-000000000000"})
    monkeypatch.setattr(ts, "peer_attached", lambda runner, serial: False)
    monkeypatch.setattr(cli, "runner", lambda: object())
    assert cli.main(["sync"]) == 0 and "not attached" in capsys.readouterr().out


def test_a_sync_that_reports_a_volume_error_exits_nonzero_and_writes_the_report(cli, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ts, "load_twin_config", lambda path=None: {"peer": "00000000-0000-0000-0000-000000000000"})
    monkeypatch.setattr(ts, "peer_attached", lambda runner, serial: True)
    monkeypatch.setattr(cli, "runner", lambda: object())
    monkeypatch.setattr(cli, "REPORT", tmp_path / "twin" / "last.json")
    monkeypatch.setattr(ts, "sync_pair", lambda runner, deep=False: {"pair": "p", "stamp": "s", "volumes": {"USER_ADMIN": {"mode": "newest", "a_to_b": 1, "b_to_a": 0, "conflicts": []}, "INSTALLER_CACHE": {"error": "not mounted"}}})
    assert cli.main(["sync"]) == 1
    assert (tmp_path / "twin" / "last.json").is_file()


def test_pairing_needs_root_an_allowed_peer_and_an_explicit_yes(cli, monkeypatch, capsys):
    monkeypatch.setattr(cli.os, "geteuid", lambda: 1000)
    assert cli.main(["pair", "--peer-serial", "SYNTHDRIVEB00002", "--yes"]) == 2                    # not root
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    assert cli.main(["pair", "--peer-serial", "SYNTHNOTLISTED001", "--yes"]) == 2                   # not this lane's own or an enrolled drive
    assert "not one of this lane's" in capsys.readouterr().out
    assert cli.main(["pair", "--peer-serial", "SYNTHDRIVEB00002"]) == 2                              # no --yes
    assert "--yes" in capsys.readouterr().out


def test_status_reports_pairing_version_and_health(cli, monkeypatch, capsys):
    monkeypatch.setattr(ts, "load_twin_config", lambda path=None: None)
    monkeypatch.setattr(ts, "read_installed", lambda root="/": {"digest": "abc", "installed_at": 5})
    monkeypatch.setattr(ts, "is_healthy", lambda digest, root="/": True)
    monkeypatch.setattr(cli, "REPORT", Path("/nonexistent/last.json"))
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert '"paired": false' in out and '"healthy": true' in out
