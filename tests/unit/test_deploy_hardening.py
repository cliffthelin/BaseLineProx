"""The installed code must not be writable by anything that runs it, so an
attacker (or a bug) in a service cannot rewrite the code that decides who gets
privileges. Checked statically against boot/provision.sh and boot/*.service,
since provisioning itself only runs on a real host (v0.2 row 54)."""
import configparser
import re
from pathlib import Path

import pytest

BOOT = Path(__file__).resolve().parents[2] / "boot"
PROVISION = (BOOT / "provision.sh").read_text()


def _units_running_installed_code():
    out = []
    for unit in sorted(BOOT.glob("*.service")):
        text = unit.read_text()
        if re.search(r"^ExecStart=\s*/opt/baseline", text, re.M):
            out.append(unit)
    return out


UNITS = _units_running_installed_code()


def test_there_are_units_to_check():
    assert len(UNITS) >= 8


@pytest.mark.parametrize("unit", UNITS, ids=lambda u: u.name)
def test_every_unit_mounts_the_installed_code_read_only(unit):
    assert re.search(r"^ReadOnlyPaths=.*?/opt/baseline\b", unit.read_text(), re.M), unit.name


@pytest.mark.parametrize("unit", UNITS, ids=lambda u: u.name)
def test_no_unit_makes_the_installed_code_writable(unit):
    for line in unit.read_text().splitlines():
        if line.startswith("ReadWritePaths="):
            assert "/opt/baseline" not in line, f"{unit.name}: {line}"


@pytest.mark.parametrize("unit", UNITS, ids=lambda u: u.name)
def test_python_does_not_try_to_write_bytecode_into_the_read_only_tree(unit):
    assert "PYTHONDONTWRITEBYTECODE=1" in unit.read_text(), unit.name


def test_provisioning_makes_the_code_root_owned_and_not_group_or_world_writable():
    assert re.search(r"^chown -R root:root /opt/baseline\b", PROVISION, re.M)
    assert re.search(r"^chmod -R go-w /opt/baseline\b", PROVISION, re.M)


def test_the_lock_down_happens_after_every_copy_into_the_tree():
    last_copy = max(m.start() for m in re.finditer(r'^cp "\$SRC/baseline/(lib|bin)/', PROVISION, re.M))
    lock = re.search(r"^chown -R root:root /opt/baseline\b", PROVISION, re.M).start()
    assert lock > last_copy


def test_verification_fails_closed_if_the_installed_code_is_writable_or_not_root_owned():
    assert "installed code is not root-owned" in PROVISION
    verify_start = PROVISION.index("Verifying staged deployment")
    check = PROVISION.index("installed code is not root-owned")
    assert check > verify_start
    # the find expression must test ownership AND group/other write bits
    block = PROVISION[check - 400:check]
    assert "! -user root" in block and "-perm -g+w" in block and "-perm -o+w" in block


def test_units_do_not_set_no_new_privileges_because_drive_admin_needs_pkexec():
    """Documented trade-off: NoNewPrivileges=true would stop pkexec, which
    Drive Administration depends on. If that changes, revisit this."""
    for unit in UNITS:
        assert "NoNewPrivileges=true" not in unit.read_text(), unit.name


def test_provisioning_tightens_state_stores_that_already_exist():
    assert re.search(r"^if \[ -d /var/lib/baseline \]; then chmod -R go-rwx /var/lib/baseline; fi", PROVISION, re.M)
