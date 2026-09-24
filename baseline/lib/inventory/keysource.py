"""Loads an explicit comparison key for cross-run manifest comparison -
never from argv (visible in `ps`/shell history) and never from an
environment variable (visible in /proc/<pid>/environ and often logged).
Only a mode-0600 file path or an already-open file descriptor number
are accepted. See baseline-drive-inventory's module docstring for the
full workflow (generate one random key outside both examined drives,
use it for both collections, delete it after the final review).

Kept separate from the CLI script itself (which has a hyphenated,
non-importable filename) so this logic is directly unit-testable,
matching this codebase's convention of thin CLI wrappers around
importable modules.
"""
import os
import stat


class KeySourceError(Exception):
    pass


def load_comparison_key(key_file=None, key_fd=None):
    """Returns the raw key bytes, or None (meaning: use a fresh
    ephemeral key) when neither key_file nor key_fd is given -
    preserving standalone ephemeral-key operation exactly as before
    this existed."""
    if key_file and key_fd is not None:
        raise KeySourceError("pass at most one of --key-file / --key-fd, not both")
    if key_file:
        mode = stat.S_IMODE(os.stat(key_file).st_mode)
        if mode != 0o600:
            raise KeySourceError(f"{key_file} is mode {oct(mode)}, refusing to read a comparison key "
                                  "from a file that isn't exactly 0600")
        with open(key_file, "rb") as f:
            key = f.read().strip()
        if not key:
            raise KeySourceError(f"{key_file} is empty")
        return key
    if key_fd is not None:
        with os.fdopen(key_fd, "rb") as f:
            key = f.read().strip()
        if not key:
            raise KeySourceError(f"fd {key_fd} produced no key bytes")
        return key
    return None
