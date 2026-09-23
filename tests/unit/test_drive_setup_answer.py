"""Unit tests for drive_setup_answer.py - the four consolidated boundary-2
concerns. Workspace/credential/answer-server tests use real local
sockets/subprocess (openssl, real TLS) deliberately - these test actual
protocol/security behavior, not something a FakeRunner should mock.
The prepare_iso_defensively postcondition logic is FakeAnswerRunner-
scripted, matching drive_setup_acquire's pattern - no real assistant
binary or real ISO needed."""
import hashlib
import secrets
import subprocess
import time
from pathlib import Path

import pytest

import drive_setup_answer as da
from pinned_client import post_pinned, FingerprintMismatch


# --------------------------------------------------------------------------
# 1. Workspace
# --------------------------------------------------------------------------

def test_create_workspace_is_mode_0700(tmp_path):
    ws = da.create_workspace(tmp_path)
    assert ws.exists()
    mode = ws.stat().st_mode & 0o777
    assert mode == 0o700


def test_inventory_and_diff(tmp_path):
    ws = da.create_workspace(tmp_path)
    before = da.inventory(ws)
    (ws / "newfile.txt").write_text("hello")
    after = da.inventory(ws)
    diff = da.diff_inventory(before, after)
    assert "newfile.txt" in diff["added"]
    assert diff["removed"] == {}


# --------------------------------------------------------------------------
# 2. Credential
# --------------------------------------------------------------------------

def test_generate_one_time_password_is_high_entropy():
    pw1 = da.generate_one_time_password()
    pw2 = da.generate_one_time_password()
    assert pw1 != pw2
    assert len(pw1) > 30
    assert b"\n" not in pw1


def test_hash_password_sha512crypt_produces_valid_shape():
    pw = b"test-password-not-real"
    h = da.hash_password_sha512crypt(pw, salt="testsalt")
    assert h.startswith("$6$")
    assert "testsalt" in h


def test_hash_password_rejects_embedded_newline():
    with pytest.raises(ValueError):
        da.hash_password_sha512crypt(b"bad\npassword", salt="x")


# --------------------------------------------------------------------------
# 3. Ephemeral answer server - real local TLS sockets, real pinning client
# --------------------------------------------------------------------------

@pytest.fixture
def self_signed_cert(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
         "-days", "1", "-nodes", "-keyout", str(key), "-out", str(cert),
         "-subj", "/CN=baseline-test-answer-server"],
        capture_output=True, check=True,
    )
    fp = subprocess.run(
        ["openssl", "x509", "-in", str(cert), "-noout", "-fingerprint", "-sha256"],
        capture_output=True, text=True, check=True,
    ).stdout.strip().split("=", 1)[1]
    return str(cert), str(key), fp


EXPECTED_MAC = "52:54:00:ba:5e:11"
EXPECTED_PRODUCT = "baseline-test-synthetic"
ANSWER = '[global]\nfqdn = "synthetic.invalid"\n'


def _fresh_server(self_signed_cert, ttl=5.0):
    cert, key, fp = self_signed_cert
    sid = secrets.token_urlsafe(24)
    sess = da.SessionState(sid, ANSWER, EXPECTED_MAC, EXPECTED_PRODUCT, ttl_seconds=ttl)
    srv = da.EphemeralAnswerServer("127.0.0.1", 0, cert, key, sess)
    srv.start()
    time.sleep(0.1)
    return srv, sess, fp


def _good_body():
    return {"network_interfaces": [{"mac": EXPECTED_MAC}], "dmi": {"system": {"name": EXPECTED_PRODUCT}}}


def test_valid_first_request_succeeds(self_signed_cert):
    srv, sess, fp = _fresh_server(self_signed_cert)
    try:
        status, body = post_pinned("127.0.0.1", srv.port, f"/answer/{sess.session_id}", _good_body(), fp)
        assert status == 200
        assert body.decode() == ANSWER
    finally:
        srv.stop()


def test_second_request_same_session_denied(self_signed_cert):
    srv, sess, fp = _fresh_server(self_signed_cert)
    try:
        post_pinned("127.0.0.1", srv.port, f"/answer/{sess.session_id}", _good_body(), fp)
        status, body = post_pinned("127.0.0.1", srv.port, f"/answer/{sess.session_id}", _good_body(), fp)
        assert status == 403
        assert body == b"already consumed"
    finally:
        srv.stop()


def test_expired_session_denied(self_signed_cert):
    srv, sess, fp = _fresh_server(self_signed_cert, ttl=0.3)
    try:
        time.sleep(0.5)
        status, _ = post_pinned("127.0.0.1", srv.port, f"/answer/{sess.session_id}", _good_body(), fp)
        assert status == 410
    finally:
        srv.stop()


def test_wrong_session_id_denied(self_signed_cert):
    srv, sess, fp = _fresh_server(self_signed_cert)
    try:
        status, _ = post_pinned("127.0.0.1", srv.port, "/answer/not-the-real-session-id", _good_body(), fp)
        assert status == 404
    finally:
        srv.stop()


def test_hardware_mismatch_denied(self_signed_cert):
    srv, sess, fp = _fresh_server(self_signed_cert)
    try:
        bad_body = {"network_interfaces": [{"mac": "de:ad:be:ef:00:00"}], "dmi": {"system": {"name": "wrong-vm"}}}
        status, body = post_pinned("127.0.0.1", srv.port, f"/answer/{sess.session_id}", bad_body, fp)
        assert status == 403
        assert body == b"hardware mismatch"
    finally:
        srv.stop()


def test_wrong_certificate_fingerprint_rejected_by_pinning(self_signed_cert):
    """A client pinned to a DIFFERENT (wrong) fingerprint must refuse
    the connection before ever seeing a response - this is the same
    property decision record 02/03's redirect-substitution test relied
    on: pinning defeats any attempt to substitute a different origin."""
    srv, sess, fp = _fresh_server(self_signed_cert)
    wrong_fp = "00" * 32
    try:
        with pytest.raises(FingerprintMismatch):
            post_pinned("127.0.0.1", srv.port, f"/answer/{sess.session_id}", _good_body(), wrong_fp)
    finally:
        srv.stop()


# --------------------------------------------------------------------------
# 4. prepare_iso_defensively - FakeAnswerRunner-scripted
# --------------------------------------------------------------------------

class FakeAnswerRunner(da.AnswerRunner):
    def __init__(self):
        self.files = {}  # path -> bytes
        self.command_responses = []
        self.calls = []

    def script(self, predicate, proc: "da.AnswerProc"):
        self.command_responses.append((predicate, proc))

    def run(self, argv, timeout=120):
        self.calls.append(list(argv))
        for predicate, proc in self.command_responses:
            if predicate(argv):
                return proc
        return da.AnswerProc(0, "", "")

    def path_exists(self, path):
        p = str(path)
        if p in self.files:
            return True
        prefix = p.rstrip("/") + "/"
        return any(k.startswith(prefix) for k in self.files)

    def is_regular_file(self, path):
        return str(path) in self.files

    def is_symlink(self, path):
        return False

    def file_size(self, path):
        return len(self.files[str(path)])

    def read_bytes(self, path):
        return self.files[str(path)]

    def resolve(self, path):
        return Path(path)

    def listdir(self, path):
        prefix = str(path).rstrip("/") + "/"
        return [Path(p) for p in self.files if p.startswith(prefix) and "/" not in p[len(prefix):]]

    def remove_tree_or_file(self, path):
        self.files.pop(str(path), None)


def _make_runner_success(output_path="/ws/prepared.iso", size=2_000_000, fp="AA:BB:CC"):
    r = FakeAnswerRunner()
    r.files[output_path] = b"x" * size
    r.script(lambda a: a[1:2] == ["prepare-iso"], da.AnswerProc(0, "prepare-iso: success", ""))
    inspect_out = (
        "Source ISO:    prepared.iso\n"
        "Product:       Proxmox VE 9.2-1\n"
        "Auto-install:  enabled\n"
        "Fetch mode:    http\n"
        "HTTP URL:      https://10.0.2.100:8443/answer/abc\n"
        f"HTTP cert fingerprint: {fp}\n"
    )
    r.script(lambda a: a[1:2] == ["inspect-iso"], da.AnswerProc(0, inspect_out, ""))
    return r


def test_prepare_iso_success_all_postconditions_pass():
    r = _make_runner_success()
    outcome = da.prepare_iso_defensively(
        r, Path("/bin/assistant"), Path("/src.iso"), None, "http",
        Path("/ws/prepared.iso"), Path("/ws/tmp"), Path("/ws"),
        expected_fetch_mode="http",
        expected_url="https://10.0.2.100:8443/answer/abc",
        expected_fingerprint="AA:BB:CC",
        min_size=1_000_000, max_size=3_000_000,
        forbidden_iso_strings=[b"should-not-appear"],
    )
    assert outcome.ok
    assert outcome.output_path is not None
    assert all(c.ok for c in outcome.postconditions)


def test_prepare_iso_fails_when_exit_code_is_0_but_stderr_shows_error():
    """Decision record 02's core finding: exit code is not trustworthy.
    A run that returns 0 but whose output contains a known failure
    pattern must still be treated as failed."""
    r = FakeAnswerRunner()
    r.script(lambda a: a[1:2] == ["prepare-iso"], da.AnswerProc(0, "", "Error: something went wrong"))
    outcome = da.prepare_iso_defensively(
        r, Path("/bin/assistant"), Path("/src.iso"), None, "http",
        Path("/ws/prepared.iso"), Path("/ws/tmp"), Path("/ws"),
        expected_fetch_mode="http", min_size=1, max_size=10,
        forbidden_iso_strings=[],
    )
    assert not outcome.ok
    failed = [c for c in outcome.postconditions if c.name == "stdout_stderr_clean"]
    assert failed and not failed[0].ok


def test_prepare_iso_fails_when_output_missing():
    r = FakeAnswerRunner()
    r.script(lambda a: a[1:2] == ["prepare-iso"], da.AnswerProc(0, "", ""))
    outcome = da.prepare_iso_defensively(
        r, Path("/bin/assistant"), Path("/src.iso"), None, "http",
        Path("/ws/prepared.iso"), Path("/ws/tmp"), Path("/ws"),
        expected_fetch_mode="http", min_size=1, max_size=10,
        forbidden_iso_strings=[],
    )
    assert not outcome.ok
    assert outcome.output_path is None


def test_prepare_iso_fails_when_forbidden_canary_present_in_iso():
    r = _make_runner_success()
    r.files["/ws/prepared.iso"] = b"...plaintext-password-canary..." + b"x" * 100
    outcome = da.prepare_iso_defensively(
        r, Path("/bin/assistant"), Path("/src.iso"), None, "http",
        Path("/ws/prepared.iso"), Path("/ws/tmp"), Path("/ws"),
        expected_fetch_mode="http",
        min_size=1, max_size=1_000_000,
        forbidden_iso_strings=[b"plaintext-password-canary"],
    )
    assert not outcome.ok
    failed = [c for c in outcome.postconditions if c.name == "no_forbidden_canaries_in_iso"]
    assert failed and not failed[0].ok


def test_prepare_iso_cleans_up_tmp_dir_on_every_path_including_failure():
    r = FakeAnswerRunner()
    r.files["/ws/tmp/leftover.tmp"] = b"partial data"
    r.script(lambda a: a[1:2] == ["prepare-iso"], da.AnswerProc(1, "", "Error: failed"))
    outcome = da.prepare_iso_defensively(
        r, Path("/bin/assistant"), Path("/src.iso"), None, "http",
        Path("/ws/prepared.iso"), Path("/ws/tmp"), Path("/ws"),
        expected_fetch_mode="http", min_size=1, max_size=10,
        forbidden_iso_strings=[],
    )
    assert not outcome.ok
    assert outcome.cleanup_ok
    assert "/ws/tmp/leftover.tmp" not in r.files


def test_prepare_iso_rejects_output_path_outside_workspace():
    r = _make_runner_success(output_path="/etc/prepared.iso")
    outcome = da.prepare_iso_defensively(
        r, Path("/bin/assistant"), Path("/src.iso"), None, "http",
        Path("/etc/prepared.iso"), Path("/ws/tmp"), Path("/ws"),
        expected_fetch_mode="http", min_size=1, max_size=3_000_000,
        forbidden_iso_strings=[],
    )
    assert not outcome.ok
    failed = [c for c in outcome.postconditions if c.name == "output_inside_workspace"]
    assert failed and not failed[0].ok
