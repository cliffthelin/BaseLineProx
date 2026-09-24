"""Ephemeral, injectable HMAC-based redaction tokens.

A production run uses a fresh os.urandom(32) key, held only in process
memory and never persisted, so two independent production runs never
produce comparable tokens for the same raw value - this is what closes
the enumeration risk a plain hash would have on low-entropy values like
IPv4 addresses or hostnames (hash every candidate, compare against the
manifest). A test injects a fixed key instead, so normalized output is
byte-identical across repeated test runs. Both properties hold at once
because the key is injectable rather than hardcoded to "always random."
"""
import hashlib
import hmac
import os


class Redactor:
    def __init__(self, key=None):
        self.key = key if key is not None else os.urandom(32)
        self._seen = {}

    @property
    def key_id(self):
        """A non-secret fingerprint of the key - safe to store in a
        manifest (it does not let anyone reconstruct the key), used
        only so a comparator (inventory/diff.py) can tell whether two
        manifests were tokenized under the same key without ever
        seeing the key itself. Deliberately a *different* hash
        (SHA-256 of the raw key) from tokenize()'s HMAC-of-value - the
        two answer different questions and must never be derivable
        from one another."""
        return hashlib.sha256(self.key).hexdigest()[:16]

    def tokenize(self, value, kind):
        """Same (kind, value) pair always maps to the same token within
        one Redactor instance (one run); a different key (a different
        run) never reproduces that token for the same value."""
        if value is None:
            return None
        cache_key = (kind, value)
        if cache_key in self._seen:
            return self._seen[cache_key]
        digest = hmac.new(self.key, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()[:12]
        token = f"{kind}:{digest}"
        self._seen[cache_key] = token
        return token

    @property
    def fields_redacted(self):
        return len(self._seen)
