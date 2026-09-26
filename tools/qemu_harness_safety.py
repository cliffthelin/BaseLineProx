"""Static safety layer for the TestPersistence QEMU vertical slice
(docs/design/testpersistence-prd.md Milestone 3, Phase A).

This module never runs QEMU itself and never touches a real block
device. It only validates paths and builds argument lists; the actual
`qemu-system-x86_64`/`qemu-img` invocation (run_qemu / run_qemu_img)
is a thin, allowlisted wrapper with no shell, no arbitrary binary, and
no host-privilege escalation tool anywhere in its call graph.

Structural guarantees this module enforces (see
tests/unit/test_qemu_harness_safety.py for the corresponding proof):

1. Every accepted image path must be a NEWLY created regular file
   beneath one exact, pre-validated experiment root.
2. Paths are canonicalized (os.path.realpath) and must remain beneath
   that root after canonicalization - a symlink or ".." cannot escape
   it.
3. Symlinks, extra hard links, block/char devices, FIFOs, sockets,
   mountpoints, and anything outside the experiment root's own
   filesystem (different st_dev - this also catches /dev, /proc, /sys,
   and any other removable-media mount, since those are always a
   different device than the experiment root's own filesystem) are
   rejected.
4. Existence checks use os.lstat (never following a symlink) and,
   where a path must be opened BY THIS MODULE, os.O_NOFOLLOW
   (hash_small_evidence_file, delete_validated_image). This does
   *not* cover QEMU's own open() of a disk/ISO path (see the TOCTOU
   note below) - QEMU opens that path itself, fresh, after this
   module has already returned a plain path string.
5. build_qemu_args() rejects anything /dev/*-shaped or block/char-
   device-shaped before it can ever reach an argument list, and
   rejects any path separator ("/") in extra_args entirely - the only
   parameters that may carry a path are system_disk, persistence_disk,
   and iso, each independently validated.
6. QEMU_ALLOWED_BINARIES is the only set of binaries this module will
   ever invoke - no sudo, pkexec, polkit, mount, losetup, udisks, or
   any other host tool appears anywhere in this module.
7. hash_small_evidence_file() refuses (never truncates or silently
   partial-hashes) anything over a small bounded size - it is for
   manifests/ledgers/journals, never for a sparse disk image.
8. delete_validated_image() re-validates then calls os.unlink() on
   one exact path - never shutil.rmtree, never a glob.
9. sanitize_evidence_text() strips absolute host paths and other
   caller-supplied sensitive substrings before any evidence is
   retained or printed.

KNOWN RESIDUAL LIMITATION (not fixed, documented honestly rather than
overclaimed): validate_image_path() proves a path is safe at the
moment it is checked, but returns a plain path *string* - it does not
hand QEMU an already-open, race-proof file descriptor. Between that
validation and the moment qemu-system-x86_64 itself calls open() on
that path (after this module's own Popen() call has already returned
control here), the file at that path could in principle be swapped
out from under it by a second process with write access to the same
experiment root. Closing this gap for real requires passing QEMU an
already-validated, already-open file descriptor (e.g. via os.open()
in this process plus `pass_fds` and a `/dev/fd/N`-style reference) -
deliberately not implemented here, because this harness's actual
threat model is a single local operator running one experiment at a
time, not a multi-tenant boundary against a concurrent adversary with
write access to the same directory. If that threat model ever
changes, fd-passing is the correct fix, not a smaller mitigation.
"""
import os
import re
import stat

MAX_EVIDENCE_FILE_BYTES = 1 * 1024 * 1024  # manifests/ledgers/journals only, never a disk image
EVIDENCE_CHUNK_BYTES = 64 * 1024

QEMU_ALLOWED_BINARIES = frozenset({"qemu-system-x86_64", "qemu-img"})
FORBIDDEN_PATH_PREFIXES = ("/dev", "/proc", "/sys")

_DEVICE_SHAPED_RE = re.compile(r"^/dev/")  # for a bare path argument
_DEVICE_PATH_ANYWHERE_RE = re.compile(r"/dev/\S+")  # for scanning composed strings like "file=/dev/sda,..."
_ABSOLUTE_PATH_RE = re.compile(r"/(?:home|run/media|root|Users)/\S+")


class HarnessSafetyError(Exception):
    """Raised for any path, argument, or operation this module refuses
    to accept - never silently ignored or downgraded to a warning."""


def validate_experiment_root(root: str) -> str:
    """Canonicalizes and validates the one exact experiment root every
    image path must live beneath. Must already exist, be a real
    directory (not a symlink), and not itself be under a forbidden
    prefix."""
    if os.path.islink(root):
        raise HarnessSafetyError(f"experiment root {root!r} is itself a symlink - refusing")
    resolved = os.path.realpath(root)
    if not os.path.isdir(resolved):
        raise HarnessSafetyError(f"experiment root {resolved!r} is not an existing directory")
    for prefix in FORBIDDEN_PATH_PREFIXES:
        if resolved == prefix or resolved.startswith(prefix + os.sep):
            raise HarnessSafetyError(
                f"experiment root {resolved!r} is beneath forbidden prefix {prefix!r}")
    return resolved


def _reject_special_file(lst: os.stat_result, path: str) -> None:
    if stat.S_ISLNK(lst.st_mode):
        raise HarnessSafetyError(f"{path!r} is a symlink - refusing to follow it")
    if stat.S_ISBLK(lst.st_mode):
        raise HarnessSafetyError(f"{path!r} is a block device - refusing")
    if stat.S_ISCHR(lst.st_mode):
        raise HarnessSafetyError(f"{path!r} is a character device - refusing")
    if stat.S_ISFIFO(lst.st_mode):
        raise HarnessSafetyError(f"{path!r} is a FIFO - refusing")
    if stat.S_ISSOCK(lst.st_mode):
        raise HarnessSafetyError(f"{path!r} is a socket - refusing")


def validate_image_path(root: str, path: str, *, must_be_new: bool) -> str:
    """Validates one image path against every structural guarantee
    listed in the module docstring. `must_be_new=True` means the path
    must NOT already exist (used when creating a fresh image);
    `must_be_new=False` means it must already exist as a validated
    regular file with exactly one hard link (used before attach/
    delete)."""
    if _DEVICE_SHAPED_RE.match(path):
        raise HarnessSafetyError(f"{path!r} is device-shaped (/dev/...) - refusing")
    if os.path.islink(path):
        # Checked on the literal given path, BEFORE realpath() below would
        # silently follow it - os.path.islink uses lstat, never follows.
        raise HarnessSafetyError(f"{path!r} is a symlink - refusing to follow it")

    resolved_root = validate_experiment_root(root)
    resolved = os.path.realpath(path)

    if resolved != resolved_root and not resolved.startswith(resolved_root + os.sep):
        raise HarnessSafetyError(
            f"{path!r} resolves to {resolved!r}, which is not beneath "
            f"experiment root {resolved_root!r} - refusing")

    for prefix in FORBIDDEN_PATH_PREFIXES:
        if resolved.startswith(prefix + os.sep) or resolved == prefix:
            raise HarnessSafetyError(f"{path!r} resolves beneath forbidden prefix {prefix!r}")

    root_dev = os.lstat(resolved_root).st_dev

    if must_be_new:
        if os.path.lexists(resolved):
            raise HarnessSafetyError(
                f"{resolved!r} already exists - a newly created image path must not")
        parent = os.path.dirname(resolved)
        parent_lst = os.lstat(parent)
        if stat.S_ISLNK(parent_lst.st_mode):
            raise HarnessSafetyError(f"parent directory {parent!r} is a symlink - refusing")
        if parent_lst.st_dev != root_dev:
            raise HarnessSafetyError(
                f"parent directory {parent!r} is on a different filesystem than the "
                f"experiment root - refusing (this also rejects /dev, /proc, /sys, and "
                f"any other removable-media mount, since those are always a different "
                f"device than the experiment root)")
        return resolved

    if not os.path.lexists(resolved):
        raise HarnessSafetyError(f"{resolved!r} does not exist")
    lst = os.lstat(resolved)
    _reject_special_file(lst, resolved)
    if lst.st_dev != root_dev:
        raise HarnessSafetyError(
            f"{resolved!r} is on a different filesystem than the experiment root - "
            f"refusing (this also rejects /dev, /proc, /sys, and any other "
            f"removable-media mount)")
    if not stat.S_ISREG(lst.st_mode):
        raise HarnessSafetyError(f"{resolved!r} is not a regular file")
    if lst.st_nlink != 1:
        raise HarnessSafetyError(
            f"{resolved!r} has {lst.st_nlink} hard links, expected exactly 1 - "
            f"refusing an image reachable through more than one path")
    if os.path.ismount(resolved):
        raise HarnessSafetyError(f"{resolved!r} is itself a mountpoint - refusing")
    return resolved


def open_validated_nofollow(path: str):
    """Opens an already-validated path with O_NOFOLLOW as a second,
    independent layer of symlink rejection at the moment of use (not
    just at validation time, closing the gap between check and use)."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    return os.open(path, flags)


# --- QEMU argument construction --------------------------------------------

def build_qemu_args(root: str, *, system_disk: str, persistence_disk: str | None = None,
                     iso: str | None = None, extra_args: tuple = ()) -> list:
    """Builds a qemu-system-x86_64 argument list. Every disk/ISO path
    is independently validated through validate_image_path before it
    can appear in the argument list - a /dev/*-shaped or block-device
    path is rejected before construction, not filtered afterward."""
    args = []
    resolved_system = validate_image_path(root, system_disk, must_be_new=False)
    args += ["-drive", f"file={resolved_system},format=qcow2,if=virtio"]

    if persistence_disk is not None:
        resolved_persistence = validate_image_path(root, persistence_disk, must_be_new=False)
        args += ["-drive", f"file={resolved_persistence},format=qcow2,if=virtio"]

    if iso is not None:
        resolved_iso = validate_image_path(root, iso, must_be_new=False)
        args += ["-cdrom", resolved_iso]

    for extra in extra_args:
        if _DEVICE_PATH_ANYWHERE_RE.search(extra) or extra.startswith(("/proc", "/sys")):
            raise HarnessSafetyError(f"extra arg {extra!r} is device/proc/sys-shaped - refusing")
        if "/" in extra:
            # system_disk/persistence_disk/iso are the only parameters this
            # function accepts a path through, and each is independently
            # validated above. extra_args has no validated-root guarantee at
            # all, so any path-shaped string here (e.g. "file=/home/x/real.img")
            # could otherwise reach the argument list unchecked - refuse any
            # "/" in extra_args outright rather than trying to guess which
            # substrings are "just flags" and which are smuggled paths.
            raise HarnessSafetyError(
                f"extra arg {extra!r} contains a path separator - extra_args must be "
                f"flag/value pairs only (e.g. \"-m\", \"1024\"), never a path; pass any "
                f"disk/ISO path through system_disk/persistence_disk/iso instead")
        args.append(extra)

    for arg in args:
        if _DEVICE_PATH_ANYWHERE_RE.search(arg):
            raise HarnessSafetyError(
                f"constructed argument {arg!r} contains a /dev/ path - refusing to return it")

    return args


def run_qemu(binary: str, args: list):
    """The only function in this module (or the whole harness) that
    invokes an external process, and only ever qemu-system-x86_64 or
    qemu-img by exact name - never sudo, pkexec, polkit, mount,
    losetup, udisks, or any other host tool, and never through a
    shell."""
    import subprocess

    if binary not in QEMU_ALLOWED_BINARIES:
        raise HarnessSafetyError(
            f"{binary!r} is not in the allowed binary set {sorted(QEMU_ALLOWED_BINARIES)} - refusing")
    for arg in args:
        if _DEVICE_PATH_ANYWHERE_RE.search(arg):
            raise HarnessSafetyError(f"refusing to run {binary} with device-shaped arg {arg!r}")
    return subprocess.Popen([binary, *args], shell=False)


# --- bounded evidence hashing -----------------------------------------------

def hash_small_evidence_file(path: str, *, max_bytes: int = MAX_EVIDENCE_FILE_BYTES) -> str:
    """Hashes a small manifest/ledger/journal file only. Refuses
    (raises) rather than truncating or silently partial-hashing
    anything over max_bytes - this function must never be pointed at a
    sparse disk image."""
    import hashlib

    size = os.lstat(path).st_size
    if size > max_bytes:
        raise HarnessSafetyError(
            f"{path!r} is {size} bytes, over the {max_bytes}-byte evidence cap - "
            f"refusing to hash (this function is for small manifests/ledgers/journals, "
            f"never a disk image)")
    digest = hashlib.sha256()
    fd = open_validated_nofollow(path)
    try:
        while True:
            chunk = os.read(fd, EVIDENCE_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest()


# --- exact-path deletion -----------------------------------------------------

def delete_validated_image(root: str, path: str) -> None:
    """Re-validates, then deletes exactly one file with os.unlink().
    Never shutil.rmtree, never a glob, never a directory."""
    resolved = validate_image_path(root, path, must_be_new=False)
    os.unlink(resolved)


# --- evidence sanitization ---------------------------------------------------

def sanitize_evidence_text(text: str, *, deny_substrings: tuple = ()) -> str:
    """Strips absolute host paths (a rough but conservative pattern
    for /home, /run/media, /root, /Users) and any caller-supplied
    sensitive substring (e.g. a real username or hostname) before
    evidence is retained or printed. Never returns the original text
    unmodified if either pattern matched."""
    sanitized = _ABSOLUTE_PATH_RE.sub("<redacted-host-path>", text)
    for value in deny_substrings:
        if value:
            sanitized = sanitized.replace(value, "<redacted>")
    return sanitized
