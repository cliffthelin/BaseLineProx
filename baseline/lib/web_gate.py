"""Operations run only when the web application asks for them (operator requirement 2026-10-01).

Every operation (a backup, a verify, a drive action, ...) calls `require(origin, op, params)` before it does
anything. `origin` is a `WebOrigin`: a short-lived proof, signed with a key that only the running web service holds,
that a logged-in session (or a schedule a logged-in session created) asked for exactly this operation with exactly
these parameters.

- The signing key is a root-only file (0600) read by the web service at start. A script, another process, a REPL, or
  a hand-built `WebOrigin` has no way to sign, so `require` refuses it. With no web service configured in the
  process (`configure` never called) EVERY operation is refused.
- A session proof is minted only for a session that is really logged in (`SessionStore.get`).
- A schedule is a record the web app signed when a logged-in session created it. Editing the stored record (the
  interval, the operation, the parameters) breaks the signature and the scheduler ignores it. Operations that need a
  human confirmation each time (hitl.CONFIRMED_ACTIONS) can never be scheduled.
- Honest limit: anyone who can read the key file (root) or the service's memory can sign. This stops everything
  else, including me.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import hitl

ORIGIN_TTL_S = 120
KEY_BYTES = 32


class GateError(Exception):
    """The gate itself is misconfigured (for example a key file anyone can read)."""


class NotFromWebApp(PermissionError):
    """An operation was attempted without a valid proof that the web application asked for it."""


def digest(op: str, params: dict) -> str:
    blob = json.dumps({"op": op, "p": params}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


@dataclass(frozen=True)
class WebOrigin:
    kind: str          # "session" or "schedule"
    op: str
    digest: str
    expires: float
    mac: str


def derive_key(root_key: bytes, purpose: str) -> bytes:
    """A separate key for each purpose, so a signature made for one thing can never be replayed as another."""
    return hmac.new(root_key, b"baseline-key|" + purpose.encode(), hashlib.sha256).digest()


def load_or_create_key(path) -> bytes:
    """The signing key. Created with mode 0600 if missing; an existing key readable by anyone else is refused."""
    path = Path(path)
    if path.exists():
        if path.stat().st_mode & 0o077:
            raise GateError(f"{path} must be readable by its owner only (mode 0600)")
        key = path.read_bytes()
        if len(key) != KEY_BYTES:
            raise GateError(f"{path} does not hold a {KEY_BYTES}-byte key")
        return key
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = os.urandom(KEY_BYTES)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, key)
    finally:
        os.close(fd)
    return key


BOT_PREFIX = "bot:"


def role_permits(role: str, op: str, params: dict) -> bool:
    """May a login with this role ask for this operation? `admin` and `operator` may ask for any (the routes
    they can reach limit them further); a `bot:<action>` role may ask for exactly its one action: an operation
    with that id, or a drive action (op "drive_action") whose action_id is that."""
    if role in ("admin", "operator"):
        return True
    if not isinstance(role, str) or not role.startswith(BOT_PREFIX):
        return False
    action = role[len(BOT_PREFIX):]
    return op == action or (op == "drive_action" and params.get("action_id") == action)


class WebGate:
    def __init__(self, key: bytes, clock=time.time, audit=None):
        if len(key) != KEY_BYTES:
            raise GateError("the signing key must be 32 bytes")
        self._key = key
        self.clock = clock
        self._audit = audit or (lambda record: None)    # hitl.AuditFile: the same append-only log

    def _mac(self, *parts) -> str:
        return hmac.new(self._key, "|".join(str(p) for p in parts).encode(), hashlib.sha256).hexdigest()

    def _origin(self, kind: str, op: str, params: dict, now: float) -> WebOrigin:
        d, expires = digest(op, params), now + ORIGIN_TTL_S
        return WebOrigin(kind, op, d, expires, self._mac("origin", kind, op, d, expires))

    @staticmethod
    def _require_login(sessions, token, now: float, op: str | None = None, params: dict | None = None) -> None:
        session = sessions.get(token, now) if isinstance(token, str) and token else None
        if session is None:
            raise NotFromWebApp("no logged-in session asked for this")
        if op is not None and not role_permits(session.role, op, params or {}):
            raise NotFromWebApp(f"this login is not authorized for {op}")

    def origin_for_session(self, sessions, token, op: str, params: dict, now: float) -> WebOrigin:
        self._require_login(sessions, token, now, op, params)
        self._audit({"event": "operation_requested", "op": op, "kind": "session"})
        return self._origin("session", op, params, now)

    # -- schedules ----------------------------------------------------------------
    def _schedule_mac(self, record: dict) -> str:
        return self._mac("schedule", record["op"], digest(record["op"], record["params"]), record["every_hours"],
                         record.get("created", 0))

    def sign_schedule(self, sessions, token, record: dict, now: float) -> dict:
        self._require_login(sessions, token, now, record["op"], record.get("params", {}))
        if record["op"] in hitl.CONFIRMED_ACTIONS:
            raise ValueError(f"{record['op']} is confirmed by a person every time and can never be scheduled")
        every = record["every_hours"]
        if isinstance(every, bool) or not isinstance(every, (int, float)) or every <= 0:
            raise ValueError("a schedule needs a positive number of hours")
        signed = {"op": record["op"], "params": dict(record["params"]), "every_hours": every, "created": now}
        signed["sig"] = self._schedule_mac(signed)
        return signed

    def origin_for_schedule(self, record: dict, now: float) -> WebOrigin:
        try:
            ok = hmac.compare_digest(str(record.get("sig", "")), self._schedule_mac(record))
        except (KeyError, TypeError):
            ok = False
        if not ok:
            raise NotFromWebApp("that schedule was not created through the web application")
        self._audit({"event": "operation_requested", "op": record["op"], "kind": "schedule"})
        return self._origin("schedule", record["op"], record["params"], now)

    # -- checking -----------------------------------------------------------------
    def check(self, origin, op: str, params: dict) -> None:
        try:
            self._check(origin, op, params)
        except NotFromWebApp as exc:
            self._audit({"event": "operation_refused", "op": op, "why": str(exc)})
            raise

    def _check(self, origin, op: str, params: dict) -> None:
        if not isinstance(origin, WebOrigin):
            raise NotFromWebApp(f"{op} runs only when the web application asks for it")
        good = hmac.compare_digest(origin.mac, self._mac("origin", origin.kind, origin.op, origin.digest, origin.expires))
        if not good:
            raise NotFromWebApp("that request was not signed by the web application")
        if origin.expires <= self.clock():
            raise NotFromWebApp("that request has expired")
        if origin.op != op or not hmac.compare_digest(origin.digest, digest(op, params)):
            raise NotFromWebApp("that request is for a different operation")


_ACTIVE: WebGate | None = None


def configure(gate: WebGate | None) -> None:
    """Called once by the web service at start. Without it, every operation is refused."""
    global _ACTIVE
    _ACTIVE = gate


def require(origin, op: str, params: dict) -> None:
    if _ACTIVE is None:
        raise NotFromWebApp(f"{op} runs only through the web application, and none is running in this process")
    _ACTIVE.check(origin, op, params)
