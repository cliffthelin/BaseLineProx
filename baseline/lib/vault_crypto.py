"""Sealing for the credential vault (encryption at rest, DR257/DR258).

A sealed value is `ENC1:` + base64(salt16 | openssl-blob | mac32). The passphrase goes through scrypt (stdlib) with the random salt to
64 bytes: the first 32 (hex) are the secret handed to `openssl enc -aes-256-ctr -pbkdf2`, the last 32 key an HMAC-SHA256 over version,
salt and the openssl blob (encrypt-then-MAC). openssl is the CLI every Debian/Proxmox host already has (the project's own convention,
config_crypto.py). The secret reaches it on an inherited pipe (`-pass fd:N`): no key, passphrase or plaintext is ever an argument.
The MAC is checked first, in constant time: a wrong passphrase and a modified token are both refused before any decryption.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import subprocess

PREFIX = "ENC1:"
MIN_PASSPHRASE = 12
_SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=64, maxmem=64 * 1024 * 1024)
_SALT = 16


class SealError(RuntimeError):
    pass


class WrongPassphrase(SealError):
    """The passphrase is wrong or the token was altered; the two cannot be told apart, by design."""


def _keys(passphrase: str, salt: bytes):
    if not isinstance(passphrase, str) or len(passphrase) < MIN_PASSPHRASE:
        raise SealError(f"the passphrase must be at least {MIN_PASSPHRASE} characters")
    material = hashlib.scrypt(passphrase.encode("utf8"), salt=salt, **_SCRYPT)
    return material[:32].hex(), material[32:]


def _openssl(decrypt: bool, secret_hex: str, data: bytes) -> bytes:
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, (secret_hex + "\n").encode())
        os.close(write_fd)
        write_fd = -1
        argv = ["openssl", "enc", "-aes-256-ctr", "-pbkdf2", "-iter", "10000", "-pass", f"fd:{read_fd}"] + (["-d"] if decrypt else [])
        done = subprocess.run(argv, input=data, capture_output=True, timeout=30, pass_fds=(read_fd,))
    finally:
        os.close(read_fd)
        if write_fd != -1:
            os.close(write_fd)
    if done.returncode != 0:
        raise SealError("the cipher could not process the value")
    return done.stdout


def seal(plaintext: str, passphrase: str) -> str:
    salt = secrets.token_bytes(_SALT)
    secret_hex, mac_key = _keys(passphrase, salt)
    blob = _openssl(False, secret_hex, plaintext.encode("utf8"))
    mac = hmac.new(mac_key, b"ENC1" + salt + blob, hashlib.sha256).digest()
    return PREFIX + base64.b64encode(salt + blob + mac).decode("ascii")


def open_sealed(token: str, passphrase: str) -> str:
    if not isinstance(token, str) or not token.startswith(PREFIX):
        raise SealError("not a sealed value")
    try:
        raw = base64.b64decode(token[len(PREFIX):], validate=True)
    except ValueError as exc:
        raise SealError("not a sealed value") from exc
    if len(raw) < _SALT + 16 + 32:
        raise SealError("not a sealed value")
    salt, blob, mac = raw[:_SALT], raw[_SALT:-32], raw[-32:]
    secret_hex, mac_key = _keys(passphrase, salt)
    if not hmac.compare_digest(mac, hmac.new(mac_key, b"ENC1" + salt + blob, hashlib.sha256).digest()):
        raise WrongPassphrase("wrong passphrase, or the stored value was altered")
    return _openssl(True, secret_hex, blob).decode("utf8")
