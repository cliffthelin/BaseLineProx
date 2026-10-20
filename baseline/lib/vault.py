"""The credential vault: where tokens and keys live (operator, 2026-10-12; DR257, DR258).

Two vaults, by whom the secret belongs to: USER_ADMIN's (`/mnt/USER_ADMIN/vault`: the host's own credentials, such as the AI provider
token the substrate uses) and USER_PERSONAL's (`/mnt/USER_PERSONAL/vault`: a person's own). A secret is one private file named for it
(`CLAUDE_CODE_OAUTH_TOKEN`), in a folder only its owner can enter. Nothing here ever puts a value in a log line, an exception message or a
status listing; the listing carries the name, the length and a short fingerprint.

A configured passphrase seals values at rest through vault_crypto (DR258). Unlocking
materializes plaintext only under /run/baseline/vault for this boot. Legacy plain
entries remain readable for compatibility; installer AI profiles always require sealing.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path

import vault_crypto
from vault_crypto import SealError, WrongPassphrase  # noqa: F401  (re-exported: callers catch v.WrongPassphrase)

RUNTIME_DIR = "/run/baseline/vault" if os.geteuid() == 0 else f"/run/user/{os.getuid()}/baseline/vault"      # RAM-backed: plaintext of an unlocked vault lives here and nowhere on the drive
VERIFIER = ".verifier"
ADMIN_VAULT = "/mnt/USER_ADMIN/vault"
PERSONAL_VAULT = "/mnt/USER_PERSONAL/vault"
_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
MIN_LENGTH, MAX_LENGTH = 8, 8192


class VaultError(RuntimeError):
    """Never carries a secret value."""


class VaultLocked(VaultError):
    """The value is sealed and no passphrase was given."""


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

    def has_passphrase(self):
        folder = self._folder()
        return folder is not None and (folder / VERIFIER).is_file()

    def check_passphrase(self, passphrase):
        folder = self._folder()
        if folder is None or not (folder / VERIFIER).is_file():
            raise VaultError("this vault has no passphrase set")
        try:
            return vault_crypto.open_sealed((folder / VERIFIER).read_text().strip(), passphrase) == "baseline-vault-verifier"
        except WrongPassphrase:
            return False

    def set_passphrase(self, passphrase):
        """First-time passphrase: writes the verifier and seals every secret already stored in plain. An existing one is not replaced."""
        if self.has_passphrase():
            raise VaultError("this vault already has a passphrase")
        folder = self._folder(create=True)
        token = vault_crypto.seal("baseline-vault-verifier", passphrase)          # also validates the passphrase's length
        for name in self.names():
            raw = (folder / name).read_text().strip()
            if not raw.startswith(vault_crypto.PREFIX):
                self._write(name, vault_crypto.seal(raw, passphrase))
        self._write_file(folder / VERIFIER, token)

    def _write_file(self, target, text):
        fd, temporary = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as handle:
                handle.write(text + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def _write(self, name, text):
        self._write_file(self._folder(create=True) / name, text)

    def put(self, name, value, passphrase=None):
        self._check_name(name)
        if (not isinstance(value, str) or not MIN_LENGTH <= len(value) <= MAX_LENGTH or any(c in value for c in "\r\n\x00")):
            raise VaultError("a secret must be one line of 8 to 8192 characters")
        folder = self._folder(create=True)
        target = folder / name
        if target.is_symlink():
            raise VaultError(f"{name} is a link; refusing to write through it")
        if self.has_passphrase():
            if passphrase is None:
                raise VaultLocked("this vault is sealed; the passphrase is needed to store a secret")
            if not self.check_passphrase(passphrase):
                raise WrongPassphrase("wrong passphrase")
            value = vault_crypto.seal(value, passphrase)
        self._write_file(target, value)

    def get(self, name, passphrase=None):
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
        raw = target.read_text().strip() or None
        if raw and raw.startswith(vault_crypto.PREFIX):
            if passphrase is None:
                raise VaultLocked(f"{name} is sealed; unlock the vault with its passphrase")
            return vault_crypto.open_sealed(raw, passphrase)
        return raw

    def unlock(self, passphrase, runtime=RUNTIME_DIR):
        """Decrypt every secret into the RAM-backed runtime folder (0700/0600) so other processes (the harness, the TUI) can read
        them for this boot. Nothing is written to the drive. Returns the names unlocked."""
        if not self.check_passphrase(passphrase):
            raise WrongPassphrase("wrong passphrase")
        runtime = Path(runtime)
        runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(runtime, 0o700)
        names = []
        for name in self.names():
            value = self.get(name, passphrase=passphrase)
            if value:
                self._write_file(runtime / name, value)
                names.append(name)
        return names

    def lock(self, runtime=RUNTIME_DIR):
        runtime = Path(runtime)
        if runtime.is_dir():
            for entry in runtime.iterdir():
                if _NAME.fullmatch(entry.name):
                    entry.unlink(missing_ok=True)

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
        folder = self._folder()
        for name in self.names():
            raw = (folder / name).read_text().strip()
            sealed = raw.startswith(vault_crypto.PREFIX)
            out.append({"name": name, "length": len(raw) if not sealed else None,
                        "fingerprint": hashlib.sha256(raw.encode()).hexdigest()[:8], "locked": sealed})
        return out


def default_vaults():
    return [Vault(PERSONAL_VAULT), Vault(ADMIN_VAULT)]


def lookup(name, *, vaults=None, environ=None, runtime=RUNTIME_DIR):
    """The value of `name`: the process environment first (an authoritative process credential), then the personal vault, then the
    admin vault. None when none holds it. An unreadable vault is skipped, never fatal here: callers report 'not set up'."""
    environ = os.environ if environ is None else environ
    if environ.get(name):
        return environ[name]
    try:                                                     # an unlocked vault's plaintext, in RAM for this boot
        unlocked = Path(runtime) / name
        if _NAME.fullmatch(name) and unlocked.is_file() and not unlocked.is_symlink() and not unlocked.stat().st_mode & 0o077:
            value = unlocked.read_text().strip()
            if value:
                return value
    except OSError:
        pass
    for vault in (default_vaults() if vaults is None else vaults):
        try:
            value = vault.get(name)
        except (VaultError, OSError):                        # sealed (locked) or unreadable: not available until unlocked
            continue
        if value:
            return value
    return None


class Unlocked:
    """A vault bound to its passphrase for one purpose (the sign-in thread storing a token). Holds the passphrase only in memory."""

    def __init__(self, vault, passphrase):
        self._vault, self._passphrase = vault, passphrase

    def put(self, name, value):
        self._vault.put(name, value, passphrase=self._passphrase)

    def get(self, name):
        return self._vault.get(name, passphrase=self._passphrase)

    def names(self):
        return self._vault.names()

    def delete(self, name):
        return self._vault.delete(name)


def build_aware_roots():
    """Installed role volumes, or encrypted parent staging on CACHE for preboot builds."""
    if ADMIN_VAULT != '/mnt/USER_ADMIN/vault' or PERSONAL_VAULT != '/mnt/USER_PERSONAL/vault':
        return ADMIN_VAULT, PERSONAL_VAULT  # explicit embedding/test overrides
    if os.path.ismount('/mnt/USER_ADMIN'):
        return ADMIN_VAULT, PERSONAL_VAULT
    import lane_files
    build = lane_files.build_drives_file().parent
    cache = next((parent for parent in (build, *build.parents) if parent.name == 'CACHE' and parent.is_mount()), None)
    if cache is not None and build.resolve().is_relative_to(cache.resolve()) and build.is_dir():
        for relative in ('parent-user-admin', 'parent-user-personal'):
            if (build / relative).is_symlink():
                raise VaultError('parent vault staging is redirected')
        return str(build / 'parent-user-admin/vault'), str(build / 'parent-user-personal/vault')
    # The UI may still report the expected partition roots while detached;
    # callers must check root_available() before any write.
    return ADMIN_VAULT, PERSONAL_VAULT


def root_available(root) -> bool:
    """True only when a role partition or the mounted build CACHE owns this path."""
    path = Path(root).absolute()
    if ADMIN_VAULT != '/mnt/USER_ADMIN/vault' and path.is_relative_to(Path(ADMIN_VAULT).absolute().parent):
        return True  # explicit embedding/test root supplied by the caller
    if PERSONAL_VAULT != '/mnt/USER_PERSONAL/vault' and path.is_relative_to(Path(PERSONAL_VAULT).absolute().parent):
        return True
    if path == Path(ADMIN_VAULT).absolute() or path.is_relative_to(Path(ADMIN_VAULT).parent):
        return os.path.ismount('/mnt/USER_ADMIN')
    if path == Path(PERSONAL_VAULT).absolute() or path.is_relative_to(Path(PERSONAL_VAULT).parent):
        return os.path.ismount('/mnt/USER_PERSONAL')
    return any(parent != Path('/') and parent.is_mount() for parent in path.parents)
