"""Output-path safety for the inventory collector's one write.

Refuses to write inside the repository checkout, /etc, /var/lib/baseline,
or /etc/pve. os.path.realpath() resolves every symlink component along
the requested path - including already-existing intermediate directories
- and collapses ".." traversal in a single call, so that one call covers
both of those attack shapes at once. What it cannot cover is a symlink or
directory swap that happens after validate_output_path() returns, which
is why atomic_write() independently re-validates immediately before it
writes, rather than trusting an earlier check. This is best-effort within
what pure Python can guarantee without OS-level openat/O_NOFOLLOW-style
primitives - noted as such rather than overclaiming a full TOCTOU close.
"""
import os
import tempfile


class OutputPathError(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _forbidden_roots(repo_root):
    return [os.path.realpath(p) for p in (repo_root, "/etc", "/var/lib/baseline", "/etc/pve")]


def _check_forbidden(resolved, repo_root):
    for root in _forbidden_roots(repo_root):
        if resolved == root or resolved.startswith(root + os.sep):
            raise OutputPathError(f"refuses to write inside {root}")


def validate_output_path(requested_path, repo_root, overwrite):
    resolved = os.path.realpath(requested_path)
    _check_forbidden(resolved, repo_root)

    if os.path.islink(requested_path):
        raise OutputPathError("refuses to write through an existing symlink at the requested path")

    if os.path.exists(resolved) and not overwrite:
        raise OutputPathError(f"{resolved} already exists; pass overwrite=True to replace it")

    return resolved


def atomic_write(resolved_path, data, overwrite):
    """Re-validates immediately before writing, then writes via a
    same-directory temp file, fsync, os.replace(), and a directory fsync
    - never a partially written file visible at the final path, and
    (canonical-repo reconciliation: matches firstboot_statemachine.py's
    _durable_write, which also fsyncs the containing directory - the
    original inventory branch's atomic_write() did not) the rename
    itself is durable against a crash immediately after, not just the
    file content."""
    if os.path.islink(resolved_path):
        raise OutputPathError("refuses to write through a symlink that appeared at the final path")
    if os.path.exists(resolved_path) and not overwrite:
        raise OutputPathError(f"{resolved_path} already exists; refusing to overwrite without --overwrite")

    directory = os.path.dirname(resolved_path) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".inventory-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, resolved_path)
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
