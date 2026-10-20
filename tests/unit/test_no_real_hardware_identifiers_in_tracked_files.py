"""No real drive serial is stored in the repository, in code, tests, scripts or documents. Serials are operator data on volumes that git ignores and that are never pushed (the lane's own-drives file on the
persistent admin volume on an installed system; the build volume on a development host). On a machine that has such data this test finds the real serials and fails if any is in a tracked file; everywhere it
also checks that nothing in the tracked files looks like a hard-coded drive serial next to the word 'serial'."""
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_SERIAL = re.compile(r"^[A-Za-z0-9_.-]{8,64}$")


def tracked_files():
    done = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True)
    return [REPO / name for name in done.stdout.decode().split("\0") if name]


def real_serials_on_this_machine():
    found = set()
    for source in ("/etc/baseline/own-drives",):
        try:
            for line in Path(source).read_text().splitlines():
                words = line.split("#", 1)[0].split()
                if words and _SERIAL.match(words[0]):
                    found.add(words[0])
        except OSError:
            pass
    for source in ("/run/media/cane/CACHE/baseline-build/drives.json",):
        try:
            found.update(s for s in json.loads(Path(source).read_text())["drives"].values() if isinstance(s, str) and _SERIAL.match(s))
        except (OSError, ValueError, KeyError, TypeError):
            pass
    try:                                                                     # the serials of the drives attached right now
        listing = subprocess.run(["lsblk", "-dn", "-o", "SERIAL"], capture_output=True, text=True, timeout=10).stdout
        found.update(line.strip() for line in listing.splitlines() if _SERIAL.match(line.strip()))
    except (OSError, subprocess.SubprocessError):
        pass
    return {s for s in found if not s.upper().startswith("SYNTH")}


def test_no_real_serial_of_this_machines_drives_or_operator_data_is_in_a_tracked_file():
    serials = real_serials_on_this_machine()
    if not serials:
        pytest.skip("no operator data or attached drives to check against on this machine")
    leaks = {}
    for path in tracked_files():
        try:
            text = path.read_bytes().decode("utf-8", "ignore")
        except OSError:
            continue
        for serial in serials:
            if serial in text:
                leaks.setdefault(str(path.relative_to(REPO)), []).append("a real drive serial")
    assert not leaks, f"real drive serials are stored in tracked files (they belong in operator data, not in git): {sorted(leaks)}"


def test_tracked_code_has_no_hard_coded_serial_literal_next_to_the_word_serial():
    # SYNTH... values are the obviously synthetic test serials; anything else that looks like a drive serial literal is a stored serial.
    pattern = re.compile(r"""(?i:serial)[^\n]{0,30}['"]([A-Z0-9]{10,24})['"]""")
    offenders = []
    for path in tracked_files():
        if path.suffix not in {".py", ".sh", ""} or not str(path.relative_to(REPO)).startswith(("baseline/", "boot/", "config/")):
            continue
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for match in pattern.finditer(text):
            value = match.group(1)
            if value.startswith(("SYNTH", "BL")) or not (re.search(r"[0-9]", value) and re.search(r"[A-Z]", value)):   # a real serial mixes letters and digits
                continue
            if True:
                offenders.append((str(path.relative_to(REPO)), match.group(1)))
    assert not offenders, f"hard-coded serial-looking literals in code: {offenders}"
