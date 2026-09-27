"""Tests for recovery_trust.py - USB challenge-response recovery trust
(decision record 76). Real mechanism for recovering access to a
specific persona's USER_PERSISTENCE when there is no credential to
check against. Per direct instruction: a previously-authorized,
physically-connected device proves trust via real challenge-response,
not a bare copyable bearer token; "must store multiple identifiers";
"not internet dependent and actually need protection from any
internet or network attempt to spoof this" - every function here is
local file I/O and subprocess calls, never a network operation.

RecoveryTrustRunner is deliberately its own small interface (binary
read/write for real signature bytes), matching drive_setup_acquire.py's
own established precedent of a domain-specific Runner rather than
extending the shared repair.Runner - so this test file defines its own
dedicated fake rather than reusing fake_runner.FakeRunner.

No real openssl subprocess is invoked in these tests - the fake
scripts every command. The real command shapes (genpkey/pkeyutl
sign/verify) were smoke-tested directly against real openssl on this
dev machine before writing this module - confirmed a tampered message
fails verification with a real, non-zero exit.
"""
from dataclasses import dataclass, field

import recovery_trust as rtr


@dataclass
class FakeProc:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class FakeRecoveryTrustRunner(rtr.RecoveryTrustRunner):
    def __init__(self):
        self.text_files: dict = {}
        self.binary_files: dict = {}
        self.dirs: set = set()
        self.command_responses: list = field(default_factory=list) if False else []
        self.calls: list = []

    def run(self, argv, timeout=15):
        self.calls.append(list(argv))
        for predicate, proc in self.command_responses:
            if predicate(argv):
                return proc
        return FakeProc(0, "", "")

    def path_exists(self, path):
        return path in self.text_files or path in self.binary_files or path in self.dirs

    def read_text(self, path):
        return self.text_files[path]

    def write_text_atomic(self, path, content):
        self.text_files[path] = content

    def read_bytes(self, path):
        return self.binary_files[path]

    def write_bytes(self, path, data):
        self.binary_files[path] = data

    def makedirs(self, path):
        self.dirs.add(path)

    def script(self, predicate, proc):
        self.command_responses.append((predicate, proc))


# -- pure argv builders -----------------------------------------------

def test_generate_keypair_argv():
    assert rtr.generate_keypair_argv("/mnt/usb/key.pem") == [
        "openssl", "genpkey", "-algorithm", "ed25519", "-out", "/mnt/usb/key.pem"]


def test_extract_public_key_argv():
    assert rtr.extract_public_key_argv("/mnt/usb/key.pem", "/tmp/pub.pem") == [
        "openssl", "pkey", "-in", "/mnt/usb/key.pem", "-pubout", "-out", "/tmp/pub.pem"]


def test_sign_argv():
    assert rtr.sign_argv("/mnt/usb/key.pem", "/tmp/msg.bin", "/tmp/sig.bin") == [
        "openssl", "pkeyutl", "-sign", "-inkey", "/mnt/usb/key.pem", "-rawin",
        "-in", "/tmp/msg.bin", "-out", "/tmp/sig.bin"]


def test_verify_argv():
    assert rtr.verify_argv("/tmp/pub.pem", "/tmp/msg.bin", "/tmp/sig.bin") == [
        "openssl", "pkeyutl", "-verify", "-pubin", "-inkey", "/tmp/pub.pem",
        "-rawin", "-in", "/tmp/msg.bin", "-sigfile", "/tmp/sig.bin"]


# -- challenge generation ------------------------------------------------

def test_generate_challenge_returns_a_real_random_hex_string():
    a = rtr.generate_challenge()
    b = rtr.generate_challenge()
    assert a != b
    assert len(a) >= 32
    int(a, 16)  # must be real hex


# -- enrollment -----------------------------------------------------------

def test_enroll_device_records_a_manifest_entry_with_multiple_identifiers():
    runner = FakeRecoveryTrustRunner()
    runner.text_files["/mnt/usb/key.pem.pub.tmp"] = "-----BEGIN PUBLIC KEY-----\nFAKE\n-----END PUBLIC KEY-----\n"
    device = rtr.enroll_device(runner, persona="admin", device_serial="USB-SERIAL-123",
                                install_id="install-abc", private_key_out_path="/mnt/usb/key.pem")
    assert device.persona == "admin"
    assert device.device_serial == "USB-SERIAL-123"
    assert device.install_id == "install-abc"
    assert "BEGIN PUBLIC KEY" in device.public_key_pem


def test_enroll_device_runs_the_real_openssl_keygen_and_export_commands():
    runner = FakeRecoveryTrustRunner()
    runner.text_files["/mnt/usb/key.pem.pub.tmp"] = "PUBKEY"
    rtr.enroll_device(runner, persona="admin", device_serial="S1", install_id="I1",
                       private_key_out_path="/mnt/usb/key.pem")
    assert ["openssl", "genpkey", "-algorithm", "ed25519", "-out", "/mnt/usb/key.pem"] in runner.calls
    assert any(c[:2] == ["openssl", "pkey"] for c in runner.calls)


def test_enroll_device_replaces_a_previous_enrollment_for_the_same_persona_and_device():
    runner = FakeRecoveryTrustRunner()
    runner.text_files["/mnt/usb/key.pem.pub.tmp"] = "PUBKEY1"
    rtr.enroll_device(runner, persona="admin", device_serial="S1", install_id="I1",
                       private_key_out_path="/mnt/usb/key.pem")
    runner.text_files["/mnt/usb/key.pem.pub.tmp"] = "PUBKEY2"
    rtr.enroll_device(runner, persona="admin", device_serial="S1", install_id="I1",
                       private_key_out_path="/mnt/usb/key.pem")
    entries = rtr._read_manifest(runner, rtr.DEFAULT_MANIFEST_PATH)
    matching = [e for e in entries if e["persona"] == "admin" and e["device_serial"] == "S1"]
    assert len(matching) == 1
    assert matching[0]["public_key_pem"] == "PUBKEY2"


def test_enroll_device_keeps_separate_entries_for_different_personas():
    runner = FakeRecoveryTrustRunner()
    runner.text_files["/mnt/usb/key.pem.pub.tmp"] = "PUBKEY"
    rtr.enroll_device(runner, persona="admin", device_serial="S1", install_id="I1",
                       private_key_out_path="/mnt/usb/key.pem")
    rtr.enroll_device(runner, persona="personal", device_serial="S1", install_id="I1",
                       private_key_out_path="/mnt/usb/key.pem")
    entries = rtr._read_manifest(runner, rtr.DEFAULT_MANIFEST_PATH)
    assert {e["persona"] for e in entries} == {"admin", "personal"}


def test_manifest_lives_on_installer_cache_not_user_persistence():
    assert rtr.DEFAULT_MANIFEST_PATH.startswith("/mnt/INSTALLER_CACHE/")


# -- finding a trusted device (multi-field matching) ------------------

def test_find_trusted_device_requires_all_three_fields_to_match():
    runner = FakeRecoveryTrustRunner()
    runner.text_files["/mnt/usb/key.pem.pub.tmp"] = "PUBKEY"
    rtr.enroll_device(runner, persona="admin", device_serial="S1", install_id="I1",
                       private_key_out_path="/mnt/usb/key.pem")

    assert rtr.find_trusted_device(runner, persona="admin", device_serial="S1", install_id="I1") is not None
    assert rtr.find_trusted_device(runner, persona="personal", device_serial="S1", install_id="I1") is None
    assert rtr.find_trusted_device(runner, persona="admin", device_serial="WRONG", install_id="I1") is None
    assert rtr.find_trusted_device(runner, persona="admin", device_serial="S1", install_id="DIFFERENT-INSTALL") is None


def test_find_trusted_device_returns_none_when_manifest_is_empty():
    runner = FakeRecoveryTrustRunner()
    assert rtr.find_trusted_device(runner, persona="admin", device_serial="S1", install_id="I1") is None


# -- sign/verify round trip (real openssl call shapes, scripted) --------

def test_sign_challenge_runs_the_real_sign_command_and_returns_hex():
    runner = FakeRecoveryTrustRunner()
    runner.binary_files["/ws/sig.bin"] = b"\xde\xad\xbe\xef"
    runner.script(lambda a: a[:2] == ["openssl", "pkeyutl"] and "-sign" in a, FakeProc(0, "", ""))
    sig_hex = rtr.sign_challenge(runner, private_key_path="/mnt/usb/key.pem",
                                  challenge="abc123", workspace="/ws")
    assert sig_hex == "deadbeef"


def test_verify_challenge_signature_true_on_real_success():
    runner = FakeRecoveryTrustRunner()
    runner.script(lambda a: a[:2] == ["openssl", "pkeyutl"] and "-verify" in a,
                  FakeProc(0, "Signature Verified Successfully\n", ""))
    ok = rtr.verify_challenge_signature(runner, public_key_pem="PUBKEY", challenge="abc123",
                                         signature_hex="deadbeef", workspace="/ws")
    assert ok is True


def test_verify_challenge_signature_false_on_real_failure():
    runner = FakeRecoveryTrustRunner()
    runner.script(lambda a: a[:2] == ["openssl", "pkeyutl"] and "-verify" in a,
                  FakeProc(1, "", "Signature Verification Failure\n"))
    ok = rtr.verify_challenge_signature(runner, public_key_pem="PUBKEY", challenge="abc123",
                                         signature_hex="deadbeef", workspace="/ws")
    assert ok is False


def test_verify_challenge_signature_writes_the_real_challenge_bytes_to_the_workspace():
    runner = FakeRecoveryTrustRunner()
    runner.script(lambda a: a[:2] == ["openssl", "pkeyutl"] and "-verify" in a,
                  FakeProc(0, "Signature Verified Successfully\n", ""))
    rtr.verify_challenge_signature(runner, public_key_pem="PUBKEY", challenge="the-real-nonce",
                                    workspace="/ws", signature_hex="ab")
    assert runner.text_files["/ws/challenge.bin"] == "the-real-nonce"
    assert runner.text_files["/ws/pub.pem"] == "PUBKEY"


# -- the full real end-to-end verification path (decision record 76's core claim) --

def test_full_challenge_response_round_trip_with_real_matching_keys_via_a_scripted_stand_in():
    """Proves the wiring end to end - a real challenge generated, a
    real sign call, a real verify call, both scripted to behave like
    real matching keys would (already smoke-tested for real against
    actual openssl before writing this module)."""
    runner = FakeRecoveryTrustRunner()
    runner.binary_files["/ws/sig.bin"] = b"\x01\x02"
    runner.script(lambda a: "-sign" in a, FakeProc(0, "", ""))
    runner.script(lambda a: "-verify" in a, FakeProc(0, "Signature Verified Successfully\n", ""))
    challenge = rtr.generate_challenge()
    sig_hex = rtr.sign_challenge(runner, private_key_path="/mnt/usb/key.pem",
                                  challenge=challenge, workspace="/ws")
    ok = rtr.verify_challenge_signature(runner, public_key_pem="PUBKEY", challenge=challenge,
                                         signature_hex=sig_hex, workspace="/ws")
    assert ok is True
