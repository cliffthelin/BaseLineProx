"""Comparison-key loading - hardened file-path open (O_NOFOLLOW|
O_CLOEXEC, fstat()-based checks on the single open descriptor: regular
file, owned by the effective user, mode exactly 0600, exactly one hard
link, exact key length) or an already-open file descriptor, never
argv, never an environment variable. Missing/wrong-length/wrong-mode/
symlinked/multi-linked keys, both-given, empty-file, and the no-args
ephemeral-mode default are all covered."""
import os

import pytest

from inventory import keysource

GOOD_KEY = bytes(range(32))  # exactly 32 bytes - the one supported length


def _write_key(tmp_path, data=GOOD_KEY, mode=0o600, name="key"):
    key_path = tmp_path / name
    key_path.write_bytes(data)
    key_path.chmod(mode)
    return key_path


def test_no_key_source_returns_none_for_ephemeral_mode():
    assert keysource.load_comparison_key() is None


def test_key_file_correct_mode_and_length_is_accepted(tmp_path):
    key_path = _write_key(tmp_path)
    assert keysource.load_comparison_key(key_file=str(key_path)) == GOOD_KEY


def test_key_file_wrong_mode_0644_is_refused(tmp_path):
    key_path = _write_key(tmp_path, mode=0o644)
    with pytest.raises(keysource.KeySourceError, match="0600"):
        keysource.load_comparison_key(key_file=str(key_path))


def test_key_file_mode_0400_is_refused(tmp_path):
    """Exactly 0600 is required - not "0600 or stricter". A file the
    loader could still read at 0400 must still be refused, so a
    looser-than-expected OR tighter-than-expected mode both surface as
    an explicit refusal rather than one succeeding silently."""
    key_path = _write_key(tmp_path, mode=0o400)
    with pytest.raises(keysource.KeySourceError, match="0600"):
        keysource.load_comparison_key(key_file=str(key_path))


def test_key_file_strips_a_single_trailing_newline(tmp_path):
    key_path = _write_key(tmp_path, data=GOOD_KEY + b"\n")
    assert keysource.load_comparison_key(key_file=str(key_path)) == GOOD_KEY


def test_empty_key_file_is_refused(tmp_path):
    key_path = _write_key(tmp_path, data=b"")
    with pytest.raises(keysource.KeySourceError, match="empty"):
        keysource.load_comparison_key(key_file=str(key_path))


def test_key_file_wrong_length_is_refused_not_padded_or_truncated(tmp_path):
    key_path = _write_key(tmp_path, data=b"too-short")
    with pytest.raises(keysource.KeySourceError, match="32"):
        keysource.load_comparison_key(key_file=str(key_path))


def test_key_file_too_long_is_refused(tmp_path):
    key_path = _write_key(tmp_path, data=GOOD_KEY + b"extra-bytes-appended-here")
    with pytest.raises(keysource.KeySourceError, match="32"):
        keysource.load_comparison_key(key_file=str(key_path))


def test_key_file_that_is_a_symlink_is_refused_not_followed(tmp_path):
    real = _write_key(tmp_path, name="real-key")
    link = tmp_path / "key-link"
    link.symlink_to(real)
    with pytest.raises(keysource.KeySourceError, match="symlink"):
        keysource.load_comparison_key(key_file=str(link))


def test_key_file_that_is_a_directory_is_refused(tmp_path):
    d = tmp_path / "not-a-file"
    d.mkdir()
    with pytest.raises(keysource.KeySourceError, match="regular file"):
        keysource.load_comparison_key(key_file=str(d))


def test_key_file_with_multiple_hard_links_is_refused(tmp_path):
    key_path = _write_key(tmp_path)
    other_link = tmp_path / "second-link"
    os.link(str(key_path), str(other_link))
    with pytest.raises(keysource.KeySourceError, match="hard link"):
        keysource.load_comparison_key(key_file=str(key_path))


def test_key_file_and_key_fd_together_is_refused(tmp_path):
    key_path = _write_key(tmp_path)
    r, w = os.pipe()
    os.write(w, GOOD_KEY)
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
    os.write(w, GOOD_KEY)
    os.close(w)
    assert keysource.load_comparison_key(key_fd=r) == GOOD_KEY


def test_key_fd_wrong_length_is_refused():
    r, w = os.pipe()
    os.write(w, b"not-the-right-length")
    os.close(w)
    with pytest.raises(keysource.KeySourceError, match="32"):
        keysource.load_comparison_key(key_fd=r)


def test_key_fd_producing_nothing_is_refused():
    r, w = os.pipe()
    os.close(w)
    with pytest.raises(keysource.KeySourceError, match="no key bytes"):
        keysource.load_comparison_key(key_fd=r)


def test_missing_key_file_raises_os_error_not_silently_none(tmp_path):
    missing = tmp_path / "does-not-exist"
    with pytest.raises(OSError):
        keysource.load_comparison_key(key_file=str(missing))


def test_key_error_messages_never_contain_the_key_bytes(tmp_path):
    """Every KeySourceError message names what was wrong (mode, length,
    link count) - never the key material itself, even when the
    refusal happens after the key was already read (wrong length)."""
    key_path = _write_key(tmp_path, data=b"a-distinctive-and-deliberately-wrong-length-value")
    with pytest.raises(keysource.KeySourceError) as exc_info:
        keysource.load_comparison_key(key_file=str(key_path))
    assert "a-distinctive-and-deliberately-wrong-length-value" not in str(exc_info.value)
