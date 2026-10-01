"""Human-in-the-loop confirmation for drive actions (v0.2 row 65).

Every drive action needs a person to confirm THAT exact request, each time, and nothing can switch that off:

- A request does not run. It produces a CHALLENGE that says exactly what will happen to which drive.
- A person confirms it by typing a phrase tied to the drive (for example `REPAIR 10AP4E`) and by entering this
  machine's root password or passphrase. The password is the real human factor: it is not shown anywhere, so a
  script that can read the challenge still cannot confirm it.
- A confirmation is single-use, bound to the session that asked and to the exact action, parameters and drive,
  slow enough to have been read (`MIN_WAIT_S`), and short-lived.
- `require()` is what the action code calls. With no valid authorization it refuses, so there is no route,
  flag or parameter that skips the check. A forged or reused authorization is refused.
- The one exception is a STANDING APPROVAL a person grants: scoped to one action and one drive, limited in time
  and number of uses, tied to the session, revocable, and gated by the same password and a typed sentence. The
  install action can never be pre-approved: installing over a drive is confirmed every time.
- A BOT account (role `bot:<action>`) is confirmed with the root password once per day per target: confirming
  with "authorize for today" lets that account run that one action on that one drive until the local day ends;
  a different drive, a different action or the next day needs a new confirmation. Bound to the account (not one
  login), in memory only, revocable, and never available for the install action.
- Every step is written to an append-only audit log; the secret never is.

This module holds state in memory only: after a restart there are no pending challenges and no approvals.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

DEFAULT_TTL_S = 300
MIN_WAIT_S = 3
AUTHORIZATION_USE_WINDOW_S = 120
MAX_PENDING = 20
MAX_FAILED_ATTEMPTS = 5
MAX_GRANT_MINUTES = 60
MAX_GRANT_USES = 5

VERBS = {
    "build_self_installer": "INSTALL",
    "repair": "REPAIR",
    "mount_volume": "MOUNT",
    "unmount_volume": "UNMOUNT",
    "update_selected": "UPDATE",
    "stamp_installer_identity": "STAMP",
}
CONFIRMED_ACTIONS = frozenset(VERBS)
NEVER_PRE_APPROVED = frozenset({"build_self_installer"})

_SECRET = secrets.token_bytes(32)


def day_key(now: float) -> str:
    """The local calendar day. A daily authorization ends when this changes."""
    return time.strftime("%Y-%m-%d", time.localtime(now))


class ConfirmationError(Exception):
    """A confirmation or approval attempt that was refused. `reason` is machine-readable: callers rate-limit
    on "phrase" and "credential" (guessing) and not on "too_fast" or "unknown"."""

    def __init__(self, message: str, reason: str = "refused"):
        super().__init__(message)
        self.reason = reason


class ConfirmationRequired(Exception):
    """An action was attempted without a valid confirmation."""


def request_digest(action_id: str, params: dict, serial: str) -> str:
    blob = json.dumps({"a": action_id, "p": params, "s": serial}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def phrase_for(action_id: str, serial: str) -> str:
    return f"{VERBS[action_id]} {serial[-6:].upper()}"


def _normalize(text) -> str:
    return " ".join(str(text).split()).upper()


def _who(session_id: str) -> str:
    return hashlib.sha256(str(session_id).encode()).hexdigest()[:10]


def _mac(nonce: str, digest: str, expires: float, kind: str) -> str:
    return hmac.new(_SECRET, f"{nonce}|{digest}|{expires}|{kind}".encode(), hashlib.sha256).hexdigest()


class Authorization:
    """Proof that a person confirmed one exact request. Minted only by a ConfirmationStore."""

    __slots__ = ("_store", "_nonce", "_digest", "_expires", "_kind", "_mac")

    def __init__(self, store, nonce: str, digest: str, expires: float, kind: str):
        self._store, self._nonce, self._digest, self._expires, self._kind = store, nonce, digest, expires, kind
        self._mac = _mac(nonce, digest, expires, kind)

    def valid_for(self, action_id: str, params: dict, serial: str) -> bool:
        """Is this authorization for exactly this request? Does not use it up."""
        genuine = hmac.compare_digest(self._mac, _mac(self._nonce, self._digest, self._expires, self._kind))
        return genuine and hmac.compare_digest(self._digest, request_digest(action_id, params, serial))


def require(authorization, action_id: str, params: dict, serial: str, *, store=None) -> None:
    """Called by the action code before it does anything. Returns None only for an action that needs no
    confirmation, or for a valid, unused, unexpired authorization for exactly this request (which it uses up).
    Anything else raises ConfirmationRequired."""
    if action_id not in CONFIRMED_ACTIONS:
        return None
    if not isinstance(authorization, Authorization):
        raise ConfirmationRequired(f"{action_id} needs a human confirmation, and none was given")
    if store is not None and not store.owns(authorization):
        raise ConfirmationRequired("that confirmation was not issued by this system")
    authorization._store._use(authorization, action_id, params, serial)


class AuditFile:
    """Append-only JSON lines. Opened with O_APPEND, mode 0600, never rewritten or truncated."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    def __call__(self, record: dict) -> None:
        line = json.dumps({"ts": time.time(), **record}, sort_keys=True) + "\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode())
        finally:
            os.close(fd)


class ConfirmationStore:
    def __init__(self, *, verify_secret, clock=time.time, ttl_s: float = DEFAULT_TTL_S,
                 min_wait_s: float = MIN_WAIT_S, audit=None):
        self._verify_secret = verify_secret
        self.clock = clock
        self.ttl_s, self.min_wait_s = ttl_s, min_wait_s
        self._audit = audit or (lambda record: None)
        self._pending: dict = {}
        self._grants: dict = {}
        self._live: dict = {}            # nonce -> authorization not yet used
        self._daily: dict = {}           # id -> {account, action, serial, day}: a bot's authorization for today
        self._lock = threading.Lock()

    # -- challenges ----------------------------------------------------------
    def _prune(self, now: float) -> None:
        for cid in [c for c, r in self._pending.items() if r["expires"] <= now]:
            del self._pending[cid]
        for gid in [g for g, r in self._grants.items() if r["expires"] <= now or r["uses_left"] <= 0]:
            del self._grants[gid]
        for nonce in [n for n, a in self._live.items() if a._expires <= now]:
            del self._live[nonce]
        today = day_key(now)
        for did in [d for d, r in self._daily.items() if r["day"] != today]:
            del self._daily[did]

    def challenge(self, session_id: str, action_id: str, params: dict, serial: str, summary: str) -> dict:
        if action_id not in CONFIRMED_ACTIONS:
            raise ValueError(f"{action_id!r} does not take a confirmation")
        with self._lock:
            now = self.clock()
            self._prune(now)
            if len(self._pending) >= MAX_PENDING:
                raise ValueError("too many pending confirmations; confirm or let them expire first")
            cid = secrets.token_urlsafe(16)
            record = {"session": session_id, "action": action_id, "params": dict(params), "serial": serial,
                      "digest": request_digest(action_id, params, serial), "phrase": phrase_for(action_id, serial),
                      "created": now, "expires": now + self.ttl_s, "failures": 0}
            self._pending[cid] = record
            self._audit({"event": "challenge", "id": cid, "action": action_id, "serial": serial, "who": _who(session_id)})
            return {"id": cid, "summary": summary, "phrase": record["phrase"],
                    "expires_in": int(self.ttl_s), "min_wait": int(self.min_wait_s)}

    def pending_request(self, challenge_id: str):
        """The exact (action, params, serial) a challenge was issued for, or None."""
        with self._lock:
            self._prune(self.clock())
            record = self._pending.get(challenge_id)
            return None if record is None else (record["action"], dict(record["params"]), record["serial"])

    def _mint(self, digest: str, kind: str, expires: float) -> Authorization:
        auth = Authorization(self, secrets.token_urlsafe(16), digest, expires, kind)
        self._live[auth._nonce] = auth
        return auth

    def _refuse(self, session_id: str, cid: str, why: str, message: str) -> None:
        self._audit({"event": "confirm_failed", "id": cid, "reason": why, "who": _who(session_id)})
        raise ConfirmationError(message, why)

    def confirm(self, session_id: str, challenge_id: str, typed, secret, *, daily_for: str | None = None) -> Authorization:
        """`daily_for`: the bot account to also authorize for the rest of today on this drive (see the module doc)."""
        with self._lock:
            now = self.clock()
            self._prune(now)
            record = self._pending.get(challenge_id)
            if record is None:
                self._refuse(session_id, challenge_id, "unknown", "that confirmation is unknown, expired or already used")
            if daily_for and record["action"] in NEVER_PRE_APPROVED:
                self._refuse(session_id, challenge_id, "never_granted",
                             f"{record['action']} is confirmed by a person every time and can never be authorized for the day")
            if not hmac.compare_digest(str(record["session"]), str(session_id)):
                self._refuse(session_id, challenge_id, "session", "that confirmation belongs to a different session")
            if now - record["created"] < self.min_wait_s:
                self._refuse(session_id, challenge_id, "too_fast",
                             f"wait {int(self.min_wait_s)} seconds and read what will happen before confirming")
            if _normalize(typed) != record["phrase"]:
                record["failures"] += 1
                if record["failures"] >= MAX_FAILED_ATTEMPTS:
                    del self._pending[challenge_id]
                self._refuse(session_id, challenge_id, "phrase", "the phrase you typed does not match")
            if not secret or not self._verify_secret(secret):
                record["failures"] += 1
                if record["failures"] >= MAX_FAILED_ATTEMPTS:
                    del self._pending[challenge_id]
                self._refuse(session_id, challenge_id, "credential", "the credential was not accepted")
            del self._pending[challenge_id]
            if daily_for:
                did = secrets.token_urlsafe(12)
                self._daily[did] = {"account": daily_for, "action": record["action"], "serial": record["serial"],
                                    "day": day_key(now)}
                self._audit({"event": "daily_authorized", "id": did, "action": record["action"],
                             "serial": record["serial"], "account": daily_for, "day": day_key(now)})
            auth = self._mint(record["digest"], "confirmation", now + AUTHORIZATION_USE_WINDOW_S)
            self._audit({"event": "confirmed", "id": challenge_id, "action": record["action"],
                         "serial": record["serial"], "who": _who(session_id)})
            return auth

    def owns(self, authorization) -> bool:
        return isinstance(authorization, Authorization) and authorization._store is self

    def _use(self, auth: Authorization, action_id: str, params: dict, serial: str) -> None:
        with self._lock:
            now = self.clock()
            live = self._live.get(auth._nonce)
            if live is not auth:
                raise ConfirmationRequired("that confirmation was already used or has expired")
            if auth._expires <= now:
                del self._live[auth._nonce]
                raise ConfirmationRequired("that confirmation has expired")
            if not auth.valid_for(action_id, params, serial):
                raise ConfirmationRequired("that confirmation is for a different request")
            del self._live[auth._nonce]
            self._audit({"event": "authorization_used", "action": action_id, "serial": serial, "kind": auth._kind})

    # -- standing approvals -----------------------------------------------------
    def grant(self, session_id: str, *, action_id: str, serial: str, minutes, max_uses, typed, secret) -> dict:
        with self._lock:
            now = self.clock()
            self._prune(now)
            if action_id in NEVER_PRE_APPROVED:
                raise ConfirmationError(f"{action_id} is confirmed by a person every time and can never be pre-approved", "never_granted")
            if action_id not in CONFIRMED_ACTIONS:
                raise ConfirmationError(f"{action_id!r} does not take a confirmation", "limits")
            if not isinstance(minutes, int) or isinstance(minutes, bool) or not 1 <= minutes <= MAX_GRANT_MINUTES:
                raise ConfirmationError(f"an approval lasts 1 to {MAX_GRANT_MINUTES} minutes", "limits")
            if not isinstance(max_uses, int) or isinstance(max_uses, bool) or not 1 <= max_uses <= MAX_GRANT_USES:
                raise ConfirmationError(f"an approval allows 1 to {MAX_GRANT_USES} uses", "limits")
            expected = f"I AUTHORIZE {VERBS[action_id]} {serial[-6:].upper()} FOR {minutes} MINUTES"
            if _normalize(typed) != expected:
                self._audit({"event": "grant_failed", "reason": "phrase", "who": _who(session_id)})
                raise ConfirmationError("the sentence you typed does not match", "phrase")
            if not secret or not self._verify_secret(secret):
                self._audit({"event": "grant_failed", "reason": "credential", "who": _who(session_id)})
                raise ConfirmationError("the credential was not accepted", "credential")
            gid = secrets.token_urlsafe(12)
            self._grants[gid] = {"session": session_id, "action": action_id, "serial": serial,
                                 "expires": now + minutes * 60, "uses_left": max_uses}
            self._audit({"event": "grant_created", "id": gid, "action": action_id, "serial": serial,
                         "minutes": minutes, "max_uses": max_uses, "who": _who(session_id)})
            return {"id": gid, "uses_left": max_uses, "expires_in": minutes * 60}

    def authorization_from_grant(self, session_id: str, action_id: str, params: dict, serial: str):
        with self._lock:
            now = self.clock()
            self._prune(now)
            for gid, g in self._grants.items():
                if (g["action"] == action_id and g["serial"] == serial and g["uses_left"] > 0
                        and hmac.compare_digest(str(g["session"]), str(session_id))):
                    g["uses_left"] -= 1
                    auth = self._mint(request_digest(action_id, params, serial), "grant", now + AUTHORIZATION_USE_WINDOW_S)
                    self._audit({"event": "grant_used", "id": gid, "action": action_id, "serial": serial,
                                 "uses_left": g["uses_left"], "who": _who(session_id)})
                    return auth
            return None

    def authorization_from_daily(self, account: str, action_id: str, params: dict, serial: str):
        """An authorization for this request if `account` was authorized for this action on this drive today."""
        with self._lock:
            now = self.clock()
            self._prune(now)
            for did, d in self._daily.items():
                if (d["action"] == action_id and d["serial"] == serial and d["day"] == day_key(now)
                        and hmac.compare_digest(d["account"], str(account))):
                    auth = self._mint(request_digest(action_id, params, serial), "daily", now + AUTHORIZATION_USE_WINDOW_S)
                    self._audit({"event": "daily_used", "id": did, "action": action_id, "serial": serial,
                                 "account": account})
                    return auth
            return None

    def list_daily(self, account: str) -> list:
        with self._lock:
            self._prune(self.clock())
            return [{"id": did, "action": d["action"], "serial": d["serial"], "day": d["day"]}
                    for did, d in self._daily.items() if hmac.compare_digest(d["account"], str(account))]

    def revoke_daily(self, daily_id: str) -> bool:
        with self._lock:
            existed = self._daily.pop(daily_id, None) is not None
            if existed:
                self._audit({"event": "daily_revoked", "id": daily_id})
            return existed

    def revoke(self, grant_id: str) -> bool:
        with self._lock:
            existed = self._grants.pop(grant_id, None) is not None
            if existed:
                self._audit({"event": "grant_revoked", "id": grant_id})
            return existed

    def list_grants(self, session_id: str) -> list:
        with self._lock:
            now = self.clock()
            self._prune(now)
            return [{"id": gid, "action": g["action"], "serial": g["serial"], "uses_left": g["uses_left"],
                     "expires_in": int(g["expires"] - now)}
                    for gid, g in self._grants.items() if hmac.compare_digest(str(g["session"]), str(session_id))]
