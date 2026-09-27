"""USB challenge-response recovery trust (decision record 76) - the
real mechanism for recovering access to a specific persona's
USER_PERSISTENCE when there is no credential to check against (a
missing/corrupted volume has no store to check a password against at
all). Per direct instruction: a previously-authorized, physically-
connected device (USB storage - a phone in file-transfer mode, or a
dedicated USB key) proves trust via real Ed25519 challenge-response,
not a bare copyable bearer token - "protection from any internet or
network attempt to spoof this" is structural here, not policy: every
function in this module is local file I/O and subprocess calls, never
a network operation, so there is nothing for a remote attacker to
talk to.

Enrollment (done once, while the target persona's volume is healthy):
a real Ed25519 keypair is generated; the private key is written to
the trusted device's own storage (never recorded anywhere else); the
public key plus several real, independent identifiers - "must store
multiple identifiers" - (the device's own hardware serial, the persona
name, an install-id unique to this Baseline installation) are recorded
in a trust manifest on INSTALLER_CACHE - a different volume from the
one being recovered, so the manifest survives exactly the scenario
where USER_PERSISTENCE itself is gone.

Recovery: a fresh, unpredictable, single-use challenge is generated
and signed by the connected device's own private key; verified against
the recorded public key. A captured old signature is useless against a
new challenge - real replay protection, not just "does a file exist."

Real command shapes (genpkey/pkeyutl -rawin sign+verify) were smoke-
tested directly against real openssl on this dev machine before this
module was written - confirmed a tampered message fails verification
with a real, non-zero exit and openssl's own error text.

RecoveryTrustRunner is deliberately its own small interface (needs
real binary read/write for signature bytes) - matches
drive_setup_acquire.py's own established precedent of a domain-
specific Runner rather than extending the shared repair.Runner.
"""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass


class RecoveryTrustRunner:
    def run(self, argv: list, timeout: float = 15):
        raise NotImplementedError

    def path_exists(self, path: str) -> bool:
        raise NotImplementedError

    def read_text(self, path: str) -> str:
        raise NotImplementedError

    def write_text_atomic(self, path: str, content: str) -> None:
        raise NotImplementedError

    def read_bytes(self, path: str) -> bytes:
        raise NotImplementedError

    def write_bytes(self, path: str, data: bytes) -> None:
        raise NotImplementedError

    def makedirs(self, path: str) -> None:
        raise NotImplementedError


class RealRecoveryTrustRunner(RecoveryTrustRunner):
    def run(self, argv, timeout=15):
        import subprocess
        from dataclasses import dataclass as _dc

        @_dc
        class _Proc:
            returncode: int = 0
            stdout: str = ""
            stderr: str = ""

        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
            return _Proc(proc.returncode, proc.stdout, proc.stderr)
        except subprocess.TimeoutExpired as exc:
            return _Proc(returncode=-1, stderr=str(exc))

    def path_exists(self, path):
        from pathlib import Path
        return Path(path).exists()

    def read_text(self, path):
        from pathlib import Path
        return Path(path).read_text()

    def write_text_atomic(self, path, content):
        from pathlib import Path
        Path(path).write_text(content)

    def read_bytes(self, path):
        from pathlib import Path
        return Path(path).read_bytes()

    def write_bytes(self, path, data):
        from pathlib import Path
        Path(path).write_bytes(data)

    def makedirs(self, path):
        from pathlib import Path
        Path(path).mkdir(parents=True, exist_ok=True)


DEFAULT_MANIFEST_PATH = "/mnt/INSTALLER_CACHE/recovery_trust/trusted_devices.json"
DEFAULT_PRIVATE_KEY_FILENAME = ".baseline-recovery-key.pem"


@dataclass
class TrustedDevice:
    persona: str
    device_serial: str
    install_id: str
    public_key_pem: str
    private_key_filename: str = DEFAULT_PRIVATE_KEY_FILENAME


def _read_manifest(runner: RecoveryTrustRunner, path: str) -> list:
    if not runner.path_exists(path):
        return []
    try:
        return json.loads(runner.read_text(path))
    except ValueError:
        return []


def _write_manifest(runner: RecoveryTrustRunner, path: str, entries: list) -> None:
    parent = path.rsplit("/", 1)[0]
    runner.makedirs(parent)
    runner.write_text_atomic(path, json.dumps(entries, indent=2))


def generate_keypair_argv(private_key_path: str) -> list:
    return ["openssl", "genpkey", "-algorithm", "ed25519", "-out", private_key_path]


def extract_public_key_argv(private_key_path: str, public_key_path: str) -> list:
    return ["openssl", "pkey", "-in", private_key_path, "-pubout", "-out", public_key_path]


def sign_argv(private_key_path: str, message_path: str, sig_path: str) -> list:
    return ["openssl", "pkeyutl", "-sign", "-inkey", private_key_path, "-rawin",
            "-in", message_path, "-out", sig_path]


def verify_argv(public_key_pem_path: str, message_path: str, sig_path: str) -> list:
    return ["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", public_key_pem_path,
            "-rawin", "-in", message_path, "-sigfile", sig_path]


def generate_challenge() -> str:
    """A fresh, unpredictable, single-use challenge - real replay
    protection, not a bare copyable secret."""
    return secrets.token_hex(32)


def enroll_device(runner: RecoveryTrustRunner, *, persona: str, device_serial: str, install_id: str,
                   private_key_out_path: str, manifest_path: str = DEFAULT_MANIFEST_PATH) -> TrustedDevice:
    """Real, one-time enrollment: generates a genuine Ed25519 keypair,
    writes the private key to the trusted device's own path
    (`private_key_out_path` - the caller resolves this to the device's
    real mountpoint), and records the public key plus real identifying
    fields in the manifest on INSTALLER_CACHE - never the private key
    itself, which never leaves the trusted device. Replaces any
    previous enrollment for the same persona+device rather than
    accumulating stale duplicates."""
    tmp_pub = private_key_out_path + ".pub.tmp"
    runner.run(generate_keypair_argv(private_key_out_path), timeout=15)
    runner.run(extract_public_key_argv(private_key_out_path, tmp_pub), timeout=15)
    public_key_pem = runner.read_text(tmp_pub)

    device = TrustedDevice(persona=persona, device_serial=device_serial, install_id=install_id,
                            public_key_pem=public_key_pem)
    entries = _read_manifest(runner, manifest_path)
    entries = [e for e in entries if not (e["persona"] == persona and e["device_serial"] == device_serial)]
    entries.append(device.__dict__)
    _write_manifest(runner, manifest_path, entries)
    return device


def find_trusted_device(runner: RecoveryTrustRunner, *, persona: str, device_serial: str, install_id: str,
                         manifest_path: str = DEFAULT_MANIFEST_PATH):
    """Real, multi-field matching - "must store multiple identifiers"
    per direct instruction. All three (persona, device serial, and
    this specific installation's own id) must match - a device
    enrolled for one persona or one installation can never recover a
    different one, even if physically connected there."""
    for entry in _read_manifest(runner, manifest_path):
        if (entry.get("persona") == persona and entry.get("device_serial") == device_serial
                and entry.get("install_id") == install_id):
            return TrustedDevice(**entry)
    return None


def sign_challenge(runner: RecoveryTrustRunner, *, private_key_path: str, challenge: str, workspace: str) -> str:
    """Signs `challenge` with the private key at `private_key_path`
    (the connected device's own mounted filesystem) using real
    openssl. Returns the real signature as hex."""
    message_path = f"{workspace}/challenge.bin"
    sig_path = f"{workspace}/sig.bin"
    runner.makedirs(workspace)
    runner.write_text_atomic(message_path, challenge)
    runner.run(sign_argv(private_key_path, message_path, sig_path), timeout=15)
    return runner.read_bytes(sig_path).hex()


def verify_challenge_signature(runner: RecoveryTrustRunner, *, public_key_pem: str, challenge: str,
                                signature_hex: str, workspace: str) -> bool:
    """Real, offline verification against the recorded public key -
    never trusts a bare "file exists" check; checks openssl's actual
    verification outcome via both its exit code and its own stdout
    text, matching this project's standing discipline of never trusting
    a single signal for an external tool's real success."""
    pub_path = f"{workspace}/pub.pem"
    message_path = f"{workspace}/challenge.bin"
    sig_path = f"{workspace}/sig.bin"
    runner.makedirs(workspace)
    runner.write_text_atomic(pub_path, public_key_pem)
    runner.write_text_atomic(message_path, challenge)
    runner.write_bytes(sig_path, bytes.fromhex(signature_hex))
    proc = runner.run(verify_argv(pub_path, message_path, sig_path), timeout=15)
    return proc.returncode == 0 and "Verified Successfully" in (proc.stdout + proc.stderr)
