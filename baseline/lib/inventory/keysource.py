"""Loads an explicit comparison key for cross-run manifest comparison -
never from argv (visible in `ps`/shell history) and never from an
environment variable (visible in /proc/<pid>/environ and often logged).
Only a hardened-open file path or an already-open file descriptor
number are accepted, and `--key-fd` is the preferred form for actual
P0/P1 collection: a descriptor never touches a directory entry at all,
so none of the path-based checks below - or their residual race
exposure - apply to it in the first place.

Key-file hardening (all of this happens on ONE open descriptor, never
a path-based stat followed by a separate open - that gap is exactly
the TOCTOU window a hardened loader must not have):

  - Opened exactly once, with O_NOFOLLOW (refuse a symlink outright,
    not merely warn) and O_CLOEXEC (the descriptor is never inherited
    by a child process this tool might spawn).
  - Every check below runs via fstat() on that same already-open
    descriptor - never a path-based stat() before or after - so
    nothing about the file can change between "checked" and "used".
  - Must be a regular file (S_ISREG), not a device, pipe, or directory
    that happened to pass O_NOFOLLOW.
  - Must be owned by the effective user running this process
    (st_uid == os.geteuid()) - a key file owned by someone else, even
    if mode 0600, is refused rather than trusted.
  - Must be mode exactly 0600 - not "not world-readable", not
    "0600 or stricter", exactly that value, so an unexpectedly looser
    OR unexpectedly stricter (e.g. 0400, which this loader still needs
    read access to) mode is refused rather than silently accepted or
    silently failing later.
  - Must have exactly one hard link (st_nlink == 1) - multiple links
    mean another path could read (or have already read) the same
    inode's content, defeating the point of a single, deliberately
    placed key file.
  - The key content, after stripping a single trailing newline (the
    common `> file` / editor convention), must be exactly
    KEY_LENGTH_BYTES long - not "at least", not "truncated to fit":
    a key of any other length is refused outright rather than silently
    padded or truncated, since either would silently produce a
    different key than the operator intended.

Key material is never printed, logged, or included in any raised
exception's message - every error here names what was wrong about the
file (mode, ownership, length, link count), never the bytes read from
it.

Kept separate from the CLI script itself (which has a hyphenated,
non-importable filename) so this logic is directly unit-testable,
matching this codebase's convention of thin CLI wrappers around
importable modules.
"""
import errno
import os
import stat

KEY_LENGTH_BYTES = 32  # 256 bits - the one supported length, not a minimum


class KeySourceError(Exception):
    pass


def _validate_length(key: bytes, source_desc: str) -> bytes:
    if len(key) != KEY_LENGTH_BYTES:
        raise KeySourceError(
            f"comparison key from {source_desc} is {len(key)} bytes, expected exactly "
            f"{KEY_LENGTH_BYTES} ({KEY_LENGTH_BYTES * 8} bits) - refusing to silently pad or truncate")
    return key


def _read_key_file_hardened(path: str) -> bytes:
    """Single open, O_NOFOLLOW|O_CLOEXEC, every check against that one
    descriptor's own fstat() result - see module docstring."""
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise KeySourceError(f"{path} is a symlink - refusing to follow it for a comparison key") from exc
        raise

    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise KeySourceError(f"{path} is not a regular file")
        if st.st_uid != os.geteuid():
            raise KeySourceError(f"{path} is not owned by the effective user running this process")
        mode = stat.S_IMODE(st.st_mode)
        if mode != 0o600:
            raise KeySourceError(f"{path} is mode {oct(mode)}, refusing to read a comparison key "
                                  "from a file that isn't exactly 0600")
        if st.st_nlink != 1:
            raise KeySourceError(f"{path} has {st.st_nlink} hard links, expected exactly 1 - "
                                  "refusing a key file reachable through more than one path")
        # Bounded read on the same already-validated descriptor - no
        # second open, no path-based re-check, generous slack only for
        # a single trailing newline.
        raw = os.read(fd, KEY_LENGTH_BYTES + 1)
    finally:
        os.close(fd)

    key = raw[:-1] if raw.endswith(b"\n") else raw
    if not key:
        raise KeySourceError(f"{path} is empty")
    return _validate_length(key, path)


def _read_key_fd(fd: int) -> bytes:
    with os.fdopen(fd, "rb") as f:
        raw = f.read()
    key = raw[:-1] if raw.endswith(b"\n") else raw
    if not key:
        raise KeySourceError(f"fd {fd} produced no key bytes")
    return _validate_length(key, f"fd {fd}")


def load_comparison_key(key_file=None, key_fd=None):
    """Returns the raw key bytes, or None (meaning: use a fresh
    ephemeral key) when neither key_file nor key_fd is given -
    preserving standalone ephemeral-key operation exactly as before
    this existed. Prefer key_fd for real P0/P1 collection - see module
    docstring."""
    if key_file and key_fd is not None:
        raise KeySourceError("pass at most one of --key-file / --key-fd, not both")
    if key_file:
        return _read_key_file_hardened(key_file)
    if key_fd is not None:
        return _read_key_fd(key_fd)
    return None
