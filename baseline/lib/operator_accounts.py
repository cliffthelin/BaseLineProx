"""Operator accounts: limited logins the owner adds in the web application (a role that can use Operations only).

- Created only through the web app, by an admin who also enters this machine's root password or passphrase.
- Baseline stores only a salted scrypt hash, never the password, in a mode-0600 file. Nothing is seeded.
- A name that already belongs to a machine account is refused, so an operator login can never shadow a real one.
- A corrupt file, a bad record or a missing file mean "no such account"; nothing here can open a door by failing.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
from pathlib import Path

MAX_OPERATORS = 5
MIN_PASSWORD = 12
MAX_PASSWORD = 128
_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{2,31}$")
_RESERVED = frozenset({"root", "admin", "administrator", "baseline", "guest", "system", "operator"})
_SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1, "maxmem": 64 * 2 ** 20, "dklen": 32}


ROLE_OPERATOR = "operator"
BOT_PREFIX = "bot:"


def known_actions() -> frozenset:
    import drive_admin
    import operations
    return frozenset(operations.OPERATIONS) | frozenset(drive_admin.ACTIONS)


def valid_role(role) -> bool:
    return role == ROLE_OPERATOR or (isinstance(role, str) and role.startswith(BOT_PREFIX)
                                     and role[len(BOT_PREFIX):] in known_actions())


def _machine_account(name: str) -> bool:
    import pwd
    try:
        pwd.getpwnam(name)
        return True
    except KeyError:
        return False


def _hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT).hex()


class OperatorAccounts:
    def __init__(self, path, is_system_user=_machine_account):
        self.path = Path(path)
        self._is_system_user = is_system_user
        self._lock = threading.Lock()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
            accounts = data["accounts"]
            return accounts if isinstance(accounts, dict) else {}
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def _save(self, accounts: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, json.dumps({"accounts": accounts}, sort_keys=True).encode())
        finally:
            os.close(fd)
        os.replace(tmp, self.path)

    def names(self) -> list:
        return sorted(self._load())

    def add(self, username, password, role=ROLE_OPERATOR) -> None:
        if not isinstance(username, str) or not _NAME_RE.match(username) or username in _RESERVED:
            raise ValueError("a name is 3 to 32 lowercase letters, digits, - or _, starting with a letter, and not a reserved word")
        if not isinstance(password, str) or not MIN_PASSWORD <= len(password) <= MAX_PASSWORD:
            raise ValueError(f"a password is {MIN_PASSWORD} to {MAX_PASSWORD} characters")
        if not valid_role(role):
            raise ValueError("a role is operator, or bot:<one action>")
        if self._is_system_user(username):
            raise ValueError(f"{username} is already a machine account; choose another name")
        with self._lock:
            accounts = self._load()
            if username in accounts:
                raise ValueError(f"{username} already exists")
            if len(accounts) >= MAX_OPERATORS:
                raise ValueError(f"at most {MAX_OPERATORS} operator accounts")
            salt = os.urandom(16)
            accounts[username] = {"salt": salt.hex(), "hash": _hash(password, salt), "role": role}
            self._save(accounts)

    def remove(self, username) -> bool:
        with self._lock:
            accounts = self._load()
            if username not in accounts:
                return False
            del accounts[username]
            self._save(accounts)
            return True

    def verify(self, username, password) -> bool:
        record = self._load().get(username) if isinstance(username, str) else None
        if not record or not isinstance(password, str) or len(password) > MAX_PASSWORD:
            return False
        try:
            return hmac.compare_digest(_hash(password, bytes.fromhex(record["salt"])), str(record["hash"]))
        except (KeyError, ValueError, TypeError):
            return False

    def role_of(self, username) -> str | None:
        record = self._load().get(username) if isinstance(username, str) else None
        role = (record or {}).get("role", ROLE_OPERATOR)
        return role if valid_role(role) else None

    def roles(self) -> dict:
        return {name: self.role_of(name) for name in self.names()}

    def authenticate(self, username, password) -> str | None:
        """The role of this account if the password is right (and the stored role is still valid), else None."""
        return self.role_of(username) if self.verify(username, password) else None
