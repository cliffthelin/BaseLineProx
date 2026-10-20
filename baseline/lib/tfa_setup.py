"""Two-factor (TOTP) enrolment for a Proxmox user, guided from the browser.

The secret is made here, shown once to the person to enter into their authenticator, and only registered with Proxmox after they prove
the authenticator produces a valid code (so a mistyped secret never locks anyone out). RFC 6238, HMAC-SHA1, 6 digits, 30 seconds: what
every authenticator app and Proxmox itself use. Nothing is stored by Baseline; Proxmox keeps the credential.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import struct
import time
from urllib.parse import quote

_USER = re.compile(r"^[A-Za-z0-9._-]{1,64}@[A-Za-z0-9._-]{1,32}$")


def check_userid(value) -> str:
    if not isinstance(value, str) or not _USER.fullmatch(value):
        raise ValueError("a Proxmox user id looks like name@realm (for example baseline@pam)")
    return value


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def totp(secret: str, when: float, step: int = 30, digits: int = 6) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", int(when) // step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 10 ** digits
    return str(number).zfill(digits)


def verify(secret: str, code: str, now: float = None, window: int = 1) -> bool:
    if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code):
        return False
    now = time.time() if now is None else now
    return any(hmac.compare_digest(totp(secret, now + 30 * d), code) for d in range(-window, window + 1))


def otpauth_uri(userid: str, secret: str, issuer: str = "Baseline") -> str:
    return (f"otpauth://totp/{quote(issuer)}:{quote(userid, safe='')}?secret={secret}&issuer={quote(issuer)}"
            "&algorithm=SHA1&digits=6&period=30")


def enroll_argv(userid: str, uri: str, code: str, description: str) -> list:
    return ["pvesh", "create", "/access/tfa", "--userid", userid, "--type", "totp", "--totp", uri, "--value", code,
            "--description", description]
