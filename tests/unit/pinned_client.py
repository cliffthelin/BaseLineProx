"""Test-only fingerprint-pinned HTTPS client (PRD §6: kept as test-only
infrastructure, not shipped in baseline/lib). Exercises the exact
pinning mechanism the answer server's threat model depends on."""
from __future__ import annotations

import hashlib
import http.client
import json
import socket
import ssl


class FingerprintMismatch(Exception):
    pass


def _pinned_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # pinning is checked manually below, not CA trust
    return ctx


def post_pinned(host: str, port: int, path: str, body: dict, expected_fingerprint_hex: str,
                 timeout: float = 5.0) -> tuple[int, bytes]:
    expected = expected_fingerprint_hex.replace(":", "").lower()
    raw_sock = socket.create_connection((host, port), timeout=timeout)
    ctx = _pinned_context()
    tls_sock = ctx.wrap_socket(raw_sock, server_hostname=host)
    try:
        der = tls_sock.getpeercert(binary_form=True)
        actual = hashlib.sha256(der).hexdigest()
        if actual != expected:
            raise FingerprintMismatch(f"presented cert fingerprint {actual} != expected {expected}")

        conn = http.client.HTTPConnection("dummy")
        conn.sock = tls_sock
        payload = json.dumps(body).encode("utf-8")
        conn.request("POST", path, body=payload, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read()
        return resp.status, data
    finally:
        tls_sock.close()
