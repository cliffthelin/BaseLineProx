"""Real, password-based encryption for the exported Master Config file
and/or specific targeted fields within it. Direct instruction: "there
should be the option to encrypt and password protect the Master Config
file or targeted fields or pages. Including backup and restore should
not bypass those encryptions and password able to decrypt."

Uses `openssl enc` - present on every real Debian/Proxmox install
already (Proxmox's own web UI depends on OpenSSL for TLS), needing no
extra package, and readable by literally any system with OpenSSL - the
same "battle tested... regardless of what OS" standard
`backup_restore.py` already follows with `tar`. AES-256-CBC with PBKDF2
key derivation and a random salt (`openssl enc`'s own modern,
recommended invocation - not its legacy weak-KDF default) with `-a`
(base64 armor) so ciphertext is always safely embeddable as a JSON
string, for the targeted-field case.

The password is never passed as a bare CLI argument (would leak via
`ps`/shell history) - callers pass `password_file`, a path to a
private, ephemeral file holding it, the same discipline
`baseline-drive-inventory`'s key handling already established for this
project (never a `--key-value`-shaped argument).

`backup_restore.py` has no dependency on this module at all (see its
own module docstring and
`test_restore_never_invokes_any_decryption_mechanism`) - an encrypted
field or file stays exactly as encrypted through a backup/restore
round-trip. Decrypting it is always this module, called explicitly,
with the real password - that is what "backup and restore should not
bypass those encryptions" requires, structurally, not just by promise.
"""
from __future__ import annotations

import secrets

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:
        def run(self, argv, timeout=10):
            raise NotImplementedError

        def write_text_atomic(self, path, content):
            raise NotImplementedError

        def read_text(self, path):
            raise NotImplementedError

        def remove(self, path):
            raise NotImplementedError


CIPHER_ID = "aes-256-cbc-pbkdf2"


class CommandResult:
    def __init__(self, ok: bool, detail: str):
        self.ok = ok
        self.detail = detail


# ---------------------------------------------------------------------------
# Whole-file encrypt/decrypt - pure argv builders + Runner-executed wrappers
# ---------------------------------------------------------------------------

def encrypt_file_argv(in_path: str, out_path: str, password_file: str) -> list:
    return ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-a",
            "-pass", f"file:{password_file}", "-in", in_path, "-out", out_path]


def decrypt_file_argv(in_path: str, out_path: str, password_file: str) -> list:
    return ["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-a",
            "-pass", f"file:{password_file}", "-in", in_path, "-out", out_path]


def encrypt_file(runner: Runner, *, in_path: str, out_path: str, password_file: str) -> CommandResult:
    proc = runner.run(encrypt_file_argv(in_path, out_path, password_file), timeout=60)
    if proc.returncode != 0:
        return CommandResult(False, f"encrypt failed: {proc.stderr.strip()}")
    return CommandResult(True, f"encrypted {in_path} to {out_path}")


def decrypt_file(runner: Runner, *, in_path: str, out_path: str, password_file: str) -> CommandResult:
    proc = runner.run(decrypt_file_argv(in_path, out_path, password_file), timeout=60)
    if proc.returncode != 0:
        return CommandResult(False, f"decrypt failed: {proc.stderr.strip()}")
    return CommandResult(True, f"decrypted {in_path} to {out_path}")


# ---------------------------------------------------------------------------
# Dotted-path access into a nested config dict ("tab.field")
# ---------------------------------------------------------------------------

def get_dotted(config: dict, path: str):
    node = config
    for part in path.split("."):
        node = node[part]
    return node


def set_dotted(config: dict, path: str, value) -> None:
    parts = path.split(".")
    node = config
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value


def find_encrypted_field_paths(config: dict, _prefix: str = "") -> list:
    """Walks a config dict and returns the dotted path of every field
    already holding an encrypted-field marker - used to know what a
    password can decrypt without the caller tracking paths separately."""
    found = []
    for key, value in config.items():
        path = f"{_prefix}.{key}" if _prefix else key
        if isinstance(value, dict) and value.get("__encrypted__") is True:
            found.append(path)
        elif isinstance(value, dict):
            found.extend(find_encrypted_field_paths(value, path))
    return found


# ---------------------------------------------------------------------------
# Targeted-field encryption - "the Master Config file or targeted
# fields or pages"
# ---------------------------------------------------------------------------

def _tmp_path(tmp_dir: str, suffix: str) -> str:
    return f"{tmp_dir}/.baseline-crypto-{secrets.token_hex(8)}{suffix}"


def encrypt_json_fields(runner: Runner, config: dict, field_paths: list, *,
                         password_file: str, tmp_dir: str = "/tmp") -> dict:
    """Returns a NEW dict (never mutates the input) with each named
    field replaced by {"__encrypted__": true, "cipher": ..., "data":
    <base64 ciphertext>}. Fields not named are returned exactly as
    they were. Every temp file this uses is removed before returning,
    success or failure alike."""
    import copy
    result = copy.deepcopy(config)
    for path in field_paths:
        plaintext = str(get_dotted(result, path))
        tmp_in = _tmp_path(tmp_dir, ".plain")
        tmp_out = _tmp_path(tmp_dir, ".enc")
        runner.write_text_atomic(tmp_in, plaintext)
        outcome = encrypt_file(runner, in_path=tmp_in, out_path=tmp_out, password_file=password_file)
        ciphertext = runner.read_text(tmp_out).strip() if outcome.ok else ""
        runner.remove(tmp_in)
        runner.remove(tmp_out)
        if outcome.ok:
            set_dotted(result, path, {"__encrypted__": True, "cipher": CIPHER_ID, "data": ciphertext})
    return result


def decrypt_json_fields(runner: Runner, config: dict, *, password_file: str,
                         tmp_dir: str = "/tmp", return_errors: bool = False):
    """Reverses encrypt_json_fields() for every encrypted field found
    (find_encrypted_field_paths()) - the caller does not need to
    remember which fields were encrypted. A field whose decryption
    fails (wrong password) is left exactly as it was - encrypted,
    never corrupted or blanked - and its path is collected in
    `errors`. Pass `return_errors=True` to get (config, errors) back;
    otherwise just the config (errors are silently dropped, matching
    this codebase's usual single-return convention for the common
    case)."""
    import copy
    result = copy.deepcopy(config)
    errors = []
    for path in find_encrypted_field_paths(result):
        entry = get_dotted(result, path)
        tmp_in = _tmp_path(tmp_dir, ".enc")
        tmp_out = _tmp_path(tmp_dir, ".plain")
        # openssl's own base64 (-a) decoder needs a trailing newline on
        # its input or it fails outright with "error reading input
        # file" (a real finding from an end-to-end smoke test, not a
        # guess) - encrypt_file()'s own -out already ends with one;
        # writing the stored ciphertext back out here needs one added.
        ciphertext = entry["data"]
        runner.write_text_atomic(tmp_in, ciphertext if ciphertext.endswith("\n") else ciphertext + "\n")
        outcome = decrypt_file(runner, in_path=tmp_in, out_path=tmp_out, password_file=password_file)
        if outcome.ok:
            set_dotted(result, path, runner.read_text(tmp_out))
            runner.remove(tmp_out)
        else:
            errors.append(path)
        runner.remove(tmp_in)
    if return_errors:
        return result, errors
    return result
