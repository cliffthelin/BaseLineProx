"""handoff.py: passphrase-encrypted packets that carry SSH host/root keys and
Baseline's private state, and an archive extraction path that must never be
steered outside its target by a crafted packet. Row 50 of the v0.2 queue.

Uses the real `gpg` (a symmetric round trip takes well under a second) with a
throwaway GNUPGHOME so the operator's keyring is never touched."""
import io
import json
import os
import shutil
import tarfile
from pathlib import Path

import pytest

import handoff

pytestmark = pytest.mark.skipif(shutil.which("gpg") is None, reason="gpg not installed")

PASS = "correct horse battery staple"


@pytest.fixture(autouse=True)
def _private_gnupg_home(tmp_path, monkeypatch):
    home = tmp_path / "gnupg"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("GNUPGHOME", str(home))


@pytest.fixture
def sources(tmp_path, monkeypatch):
    """Point the packet's source lists at a throwaway fake host."""
    host = tmp_path / "host"
    (host / "etc-baseline").mkdir(parents=True)
    (host / "etc-baseline" / "harness.env").write_text("TOKEN=SECRET-TOKEN-VALUE\n")
    (host / "etc-baseline" / "interface_aliases.json").write_text("{}")
    (host / "hostname").write_text("pve1\n")
    monkeypatch.setattr(handoff, "_DIR_SOURCES", [(str(host / "etc-baseline"), "etc-baseline")])
    monkeypatch.setattr(handoff, "_FILE_SOURCES", [(str(host / "hostname"), "hostname")])
    monkeypatch.setattr(handoff, "_AUTHORIZED_KEYS_SRC", str(host / "no-such-authorized-keys"))
    return host


def _tar_gz(path: Path, entries):
    """entries: list of (name, bytes|None, kind) with kind in file|symlink|dir|device."""
    with tarfile.open(path, "w:gz") as tf:
        for name, data, kind in entries:
            info = tarfile.TarInfo(name)
            if kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = data
                tf.addfile(info)
            elif kind == "dir":
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tf.addfile(info)
            elif kind == "device":
                info.type = tarfile.CHRTYPE
                tf.addfile(info)
            else:
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))


def _manifest(**over):
    m = {"host_label": "pve1", "created": "2026-09-30T00:00:00+0000", "files_included": ["hostname"]}
    m.update(over)
    return json.dumps(m).encode()


def _serve_archive(monkeypatch, tmp_path, entries):
    """Make open_packet 'decrypt' to a crafted archive instead of a real packet."""
    crafted = tmp_path / "crafted.tar.gz"
    _tar_gz(crafted, entries)
    monkeypatch.setattr(handoff, "decrypt", lambda enc, arch, pw: shutil.copy(crafted, arch))
    enc = tmp_path / "x.gpg"
    enc.write_bytes(b"ignored")
    return enc


# --- the real round trip ----------------------------------------------------

def test_a_packet_round_trips_with_the_right_passphrase(tmp_path, sources):
    out = tmp_path / "packet.gpg"
    handoff.create_packet("pve1", out, PASS)
    manifest = handoff.open_packet(out, PASS, tmp_path / "restored")
    assert manifest["host_label"] == "pve1"
    assert (tmp_path / "restored" / "hostname").read_text() == "pve1\n"
    assert "SECRET-TOKEN-VALUE" in (tmp_path / "restored" / "etc-baseline" / "harness.env").read_text()
    assert manifest["has_harness_token"] is True


def test_the_packet_on_disk_does_not_contain_the_plaintext(tmp_path, sources):
    out = tmp_path / "packet.gpg"
    handoff.create_packet("pve1", out, PASS)
    raw = out.read_bytes()
    assert b"SECRET-TOKEN-VALUE" not in raw and b"harness.env" not in raw and PASS.encode() not in raw


def test_the_packet_file_is_private(tmp_path, sources):
    out = tmp_path / "packet.gpg"
    handoff.create_packet("pve1", out, PASS)
    assert (out.stat().st_mode & 0o777) == 0o600


def test_a_wrong_passphrase_raises_and_extracts_nothing(tmp_path, sources):
    out = tmp_path / "packet.gpg"
    handoff.create_packet("pve1", out, PASS)
    with pytest.raises(RuntimeError, match="wrong passphrase"):
        handoff.open_packet(out, "not it", tmp_path / "restored")
    assert not (tmp_path / "restored").exists() or not any((tmp_path / "restored").iterdir())


def test_a_file_that_is_not_a_packet_raises(tmp_path):
    junk = tmp_path / "junk.gpg"
    junk.write_bytes(b"this is not an encrypted packet")
    with pytest.raises(RuntimeError):
        handoff.open_packet(junk, PASS, tmp_path / "restored")


def test_an_empty_passphrase_is_refused_and_nothing_is_written(tmp_path, sources):
    out = tmp_path / "packet.gpg"
    with pytest.raises(ValueError, match="passphrase"):
        handoff.create_packet("pve1", out, "")
    assert not out.exists()


def test_opening_with_an_empty_passphrase_is_refused(tmp_path, sources):
    out = tmp_path / "packet.gpg"
    handoff.create_packet("pve1", out, PASS)
    with pytest.raises(ValueError, match="passphrase"):
        handoff.open_packet(out, "", tmp_path / "restored")


# --- the passphrase never travels in argv ----------------------------------

def test_the_passphrase_goes_in_on_stdin_never_in_argv(tmp_path, monkeypatch):
    calls = []

    class Done:
        returncode = 0
        stderr = b""

    def fake_run(argv, **kw):
        calls.append((list(argv), kw.get("input")))
        return Done()

    monkeypatch.setattr(handoff.subprocess, "run", fake_run)
    handoff.encrypt(tmp_path / "a", tmp_path / "b", PASS)
    handoff.decrypt(tmp_path / "b", tmp_path / "c", PASS)
    for argv, stdin in calls:
        assert not any(PASS in arg for arg in argv)
        assert "--passphrase-fd" in argv and stdin == PASS.encode()


# --- plaintext does not linger ----------------------------------------------

def test_no_plaintext_staging_is_left_behind(tmp_path, sources, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(handoff.tempfile, "tempdir", str(scratch))
    handoff.create_packet("pve1", tmp_path / "packet.gpg", PASS)
    assert list(scratch.iterdir()) == []


def test_staging_is_cleaned_up_even_when_encryption_fails(tmp_path, sources, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(handoff.tempfile, "tempdir", str(scratch))
    monkeypatch.setattr(handoff, "encrypt", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("gpg failed")))
    with pytest.raises(RuntimeError):
        handoff.create_packet("pve1", tmp_path / "packet.gpg", PASS)
    assert list(scratch.iterdir()) == []


# --- a crafted archive can never write outside the target -------------------

@pytest.mark.parametrize("name", ["../escape.txt", "../../escape.txt", "sub/../../escape.txt", "/tmp/escape-abs.txt"])
def test_path_traversal_and_absolute_entries_are_rejected(tmp_path, monkeypatch, name):
    enc = _serve_archive(monkeypatch, tmp_path, [(handoff.MANIFEST_NAME, _manifest(), "file"),
                                                 (name, b"pwned", "file")])
    target = tmp_path / "restored"
    with pytest.raises(handoff.HandoffError):
        handoff.open_packet(enc, PASS, target)
    assert not (tmp_path / "escape.txt").exists()
    assert not Path("/tmp/escape-abs.txt").exists()


def test_a_symlink_pointing_outside_cannot_be_used_to_write_outside(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    enc = _serve_archive(monkeypatch, tmp_path, [
        (handoff.MANIFEST_NAME, _manifest(), "file"),
        ("link", str(outside), "symlink"),
        ("link/pwned.txt", b"pwned", "file"),
    ])
    with pytest.raises(handoff.HandoffError):
        handoff.open_packet(enc, PASS, tmp_path / "restored")
    assert list(outside.iterdir()) == []


def test_device_nodes_are_rejected(tmp_path, monkeypatch):
    enc = _serve_archive(monkeypatch, tmp_path, [(handoff.MANIFEST_NAME, _manifest(), "file"),
                                                 ("dev-null", None, "device")])
    with pytest.raises(handoff.HandoffError):
        handoff.open_packet(enc, PASS, tmp_path / "restored")


def test_a_bad_entry_leaves_nothing_extracted_at_all(tmp_path, monkeypatch):
    """A benign entry that comes before the bad one must not be left behind."""
    enc = _serve_archive(monkeypatch, tmp_path, [
        (handoff.MANIFEST_NAME, _manifest(), "file"),
        ("hostname", b"pve1\n", "file"),
        ("../escape.txt", b"pwned", "file"),
    ])
    target = tmp_path / "restored"
    with pytest.raises(handoff.HandoffError):
        handoff.open_packet(enc, PASS, target)
    assert not target.exists() or list(target.iterdir()) == []


# --- manifest validation ----------------------------------------------------

def test_a_packet_without_a_manifest_raises_a_clear_error(tmp_path, monkeypatch):
    enc = _serve_archive(monkeypatch, tmp_path, [("hostname", b"pve1\n", "file")])
    with pytest.raises(handoff.HandoffError, match="manifest"):
        handoff.open_packet(enc, PASS, tmp_path / "restored")
    assert not (tmp_path / "restored").exists() or list((tmp_path / "restored").iterdir()) == []


@pytest.mark.parametrize("raw", [b"not json", b"[]", b'"str"', b"null"])
def test_a_manifest_that_is_not_an_object_is_rejected(tmp_path, monkeypatch, raw):
    enc = _serve_archive(monkeypatch, tmp_path, [(handoff.MANIFEST_NAME, raw, "file")])
    with pytest.raises(handoff.HandoffError):
        handoff.open_packet(enc, PASS, tmp_path / "restored")


@pytest.mark.parametrize("over", [
    {"host_label": 5}, {"host_label": ""}, {"files_included": "hostname"}, {"files_included": [1]},
    {"files_included": ["../etc/passwd"]}, {"files_included": ["/etc/passwd"]},
])
def test_a_manifest_with_the_wrong_shape_is_rejected_before_extraction(tmp_path, monkeypatch, over):
    enc = _serve_archive(monkeypatch, tmp_path, [(handoff.MANIFEST_NAME, _manifest(**over), "file"),
                                                 ("hostname", b"pve1\n", "file")])
    target = tmp_path / "restored"
    with pytest.raises(handoff.HandoffError):
        handoff.open_packet(enc, PASS, target)
    assert not target.exists() or list(target.iterdir()) == []


def test_an_oversized_manifest_is_refused_without_reading_it_all(tmp_path, monkeypatch):
    big = b'{"host_label": "' + b"a" * (2 * 1024 * 1024) + b'", "files_included": []}'
    enc = _serve_archive(monkeypatch, tmp_path, [(handoff.MANIFEST_NAME, big, "file")])
    with pytest.raises(handoff.HandoffError, match="too large"):
        handoff.open_packet(enc, PASS, tmp_path / "restored")
