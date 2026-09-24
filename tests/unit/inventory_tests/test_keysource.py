"""Comparison-key loading - file path (mode-0600 enforced) or an
already-open file descriptor, never argv, never an environment
variable. Missing keys, both-given, empty-file, and the no-args
ephemeral-mode default are all covered."""
import os

import pytest

from inventory import keysource


def test_no_key_source_returns_none_for_ephemeral_mode():
    assert keysource.load_comparison_key() is None


def test_key_file_wrong_mode_is_refused(tmp_path):
    key_path = tmp_path / "key"
    key_path.write_bytes(b"a-real-key")
    key_path.chmod(0o644)
    with pytest.raises(keysource.KeySourceError, match="0600"):
        keysource.load_comparison_key(key_file=str(key_path))


def test_key_file_mode_0600_is_accepted(tmp_path):
    key_path = tmp_path / "key"
    key_path.write_bytes(b"a-real-key")
    key_path.chmod(0o600)
    assert keysource.load_comparison_key(key_file=str(key_path)) == b"a-real-key"


def test_key_file_strips_trailing_whitespace_and_newline(tmp_path):
    key_path = tmp_path / "key"
    key_path.write_bytes(b"a-real-key\n")
    key_path.chmod(0o600)
    assert keysource.load_comparison_key(key_file=str(key_path)) == b"a-real-key"


def test_empty_key_file_is_refused(tmp_path):
    key_path = tmp_path / "key"
    key_path.write_bytes(b"")
    key_path.chmod(0o600)
    with pytest.raises(keysource.KeySourceError, match="empty"):
        keysource.load_comparison_key(key_file=str(key_path))


def test_key_file_and_key_fd_together_is_refused(tmp_path):
    key_path = tmp_path / "key"
    key_path.write_bytes(b"x")
    key_path.chmod(0o600)
    r, w = os.pipe()
    os.write(w, b"y")
    os.close(w)
    try:
        with pytest.raises(keysource.KeySourceError, match="at most one"):
            keysource.load_comparison_key(key_file=str(key_path), key_fd=r)
    finally:
        try:
            os.close(r)
        except OSError:
            pass


def test_key_fd_reads_key_bytes():
    r, w = os.pipe()
    os.write(w, b"fd-provided-key")
    os.close(w)
    assert keysource.load_comparison_key(key_fd=r) == b"fd-provided-key"


def test_key_fd_producing_nothing_is_refused():
    r, w = os.pipe()
    os.close(w)
    with pytest.raises(keysource.KeySourceError, match="no key bytes"):
        keysource.load_comparison_key(key_fd=r)


def test_missing_key_file_raises_os_error_not_silently_none(tmp_path):
    missing = tmp_path / "does-not-exist"
    with pytest.raises(OSError):
        keysource.load_comparison_key(key_file=str(missing))
