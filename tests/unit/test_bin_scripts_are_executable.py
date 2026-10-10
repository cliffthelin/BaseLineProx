"""Every baseline/bin entry point must be recorded executable (100755) in git.

The repo is developed on an NTFS drive where every file reads back as mode 777, so a script committed as 100644
still runs there - and silently ships non-executable from any POSIX checkout or ISO built from one, where the
systemd units that ExecStart these scripts would fail. Found 2026-10-10: 20 entry points were 100644, including
baseline-firstboot (ExecStart of baseline-firstboot.service) and baseline-kiosk-gate."""
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _index_modes():
    try:
        out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-s", "baseline/bin"], capture_output=True,
                             text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return {line.split("\t", 1)[1]: line.split()[0] for line in out.splitlines() if "\t" in line}


def test_every_bin_entry_point_with_a_shebang_is_committed_executable():
    modes = _index_modes()
    wrong = sorted(path for path, mode in modes.items()
                   if mode != "100755" and (REPO / path).read_bytes()[:2] == b"#!")
    assert not wrong, f"committed non-executable: {wrong}"
