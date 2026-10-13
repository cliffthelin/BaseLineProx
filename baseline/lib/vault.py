"""The credential vault: where tokens and keys live (operator, 2026-10-12; DR257, DR258).

Two vaults, by whom the secret belongs to: USER_ADMIN's (`/mnt/USER_ADMIN/vault`: the host's own credentials, such as the AI provider
token the substrate uses) and USER_PERSONAL's (`/mnt/USER_PERSONAL/vault`: a person's own). A secret is one private file named for it
(`CLAUDE_CODE_OAUTH_TOKEN`), in a folder only its owner can enter. Nothing here ever puts a value in a log line, an exception message or a
status listing; the listing carries the name, the length and a short fingerprint.

Honest scope: v1 protects by file mode and by living on the role volume, not by encryption at rest. Encryption needs the key source DR257
leaves open (the admin passphrase verifier); until then the vault is as private as the volume's own access control.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path

ADMIN_VAULT = "/mnt/USER_ADMIN/vault"
PERSONAL_VAULT = "/mnt/USER_PERSONAL/vault"
_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
MIN_LENGTH, MAX_LENGTH = 8, 8192


class VaultError(RuntimeError):
    """Never carries a secret value."""


class Vault:
    def __init__(self, root):
        self.root = Path(root)

    def _check_name(self, name):
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise VaultError("a secret name is upper-case letters, digits and underscores, 3 to 64 characters, starting with a letter")

    def _folder(self, create=False):
        if not self.root.exists():
            if not create:
                return None
            self.root.mkdir(mode=0o700, parents=True)
        info = self.root.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise VaultError(f"{self.root} is not a plain folder")
        if info.st_mode & 0o077:
            raise VaultError(f"{self.root} is accessible to others; it must be mode 0700")
        return self.root

    def put(self, name, value):
        self._check_name(name)
        if (not isinstance(value, str) or not MIN_LENGTH <= len(value) <= MAX_LENGTH or any(c in value for c in "\r\n\x00")):
            raise VaultError("a secret must be one line of 8 to 8192 characters")
        folder = self._folder(create=True)
        target = folder / name
        if target.is_symlink():
            raise VaultError(f"{name} is a link; refusing to write through it")
        fd, temporary = tempfile.mkstemp(prefix=name + ".", suffix=".tmp", dir=folder)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as handle:
                handle.write(value + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def get(self, name):
        self._check_name(name)
        folder = self._folder()
        if folder is None:
            return None
        target = folder / name
        try:
            info = target.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise VaultError(f"{name} is not a plain file; refusing to read it")
        if info.st_mode & 0o077:
            raise VaultError(f"{name} is accessible to others; it must be mode 0600")
        return target.read_text().strip() or None

    def delete(self, name):
        self._check_name(name)
        folder = self._folder()
        if folder is not None:
            (folder / name).unlink(missing_ok=True)

    def names(self):
        folder = self._folder()
        if folder is None:
            return []
        return sorted(p.name for p in folder.iterdir() if _NAME.fullmatch(p.name) and p.is_file() and not p.is_symlink())

    def status(self):
        """[{name, length, fingerprint}] - what the operator may see about each secret."""
        out = []
        for name in self.names():
            value = self.get(name) or ""
            out.append({"name": name, "length": len(value), "fingerprint": hashlib.sha256(value.encode()).hexdigest()[:8]})
        return out


def default_vaults():
    return [Vault(PERSONAL_VAULT), Vault(ADMIN_VAULT)]


def lookup(name, *, vaults=None, environ=None):
    """The value of `name`: the process environment first (an authoritative process credential), then the personal vault, then the
    admin vault. None when none holds it. An unreadable vault is skipped, never fatal here: callers report 'not set up'."""
    environ = os.environ if environ is None else environ
    if environ.get(name):
        return environ[name]
    for vault in (default_vaults() if vaults is None else vaults):
        try:
            value = vault.get(name)
        except (VaultError, OSError):
            continue
        if value:
            return value
    return None
