import pytest

import hardware


def _valid_minimal_inxi():
    return [
        {"System": [{"Kernel": "6.1.0", "Distro": "Ubuntu"}]},
        {"Machine": [{"Type": "Desktop", "System": "Test system"}]},
        {"CPU": [{"model": "Test CPU", "cpus": 8}]},
    ]


@pytest.mark.parametrize("raw", [None, {}, [], ["unexpected"], [{"Graphics": []}]])
def test_normalize_rejects_inventory_without_required_system_and_cpu_sections(raw):
    with pytest.raises(hardware.HardwareInventoryError):
        hardware.normalize(raw)


def test_normalize_accepts_absent_optional_sections():
    normalized = hardware.normalize(_valid_minimal_inxi())
    assert normalized["cpu"] == {"model": "Test CPU", "cores": 8}
    assert normalized["network"] == {}
    assert normalized["drives"] == {}


def test_normalize_rejects_required_sections_with_no_observations():
    raw = _valid_minimal_inxi()
    raw[0] = {"System": []}
    with pytest.raises(hardware.HardwareInventoryError):
        hardware.normalize(raw)


def test_normalize_rejects_malformed_optional_section_instead_of_crashing_later():
    raw = _valid_minimal_inxi() + [{"Network": None}]
    with pytest.raises(hardware.HardwareInventoryError, match="invalid shape"):
        hardware.normalize(raw)


def _with_repos(repos):
    return _valid_minimal_inxi() + [{"Repos": repos}]


# The exact shape captured from `inxi -Fmrsiaxxxz --output json` on the 2026-10-10 offline rehearsal (Proxmox VE
# 9.2 under QEMU with two apt sources): objects for each sources file, each followed by a list of its raw lines.
_REAL_REPOS = [
    {"pkgs": 947, "pm": "dpkg", "Packages": "", "tools": "apt,apt-get", "libs": 530},
    {"Active apt repos in": "/etc/apt/sources.list.d/baseline-installer-cache.list"},
    ["deb [trusted=yes] file:/mnt/INSTALLER_CACHE/installer/expanded/baseline-cache/apt ./"],
    {"Active apt repos in": "/etc/apt/sources.list.d/debian.sources"},
    ["deb http://deb.debian.org/debian/ trixie main contrib non-free-firmware",
     "deb http://deb.debian.org/debian/ trixie-updates main contrib non-free-firmware"],
]


def test_the_real_repos_section_with_nested_line_lists_is_accepted():
    """Every machine with more than one apt source failed the Hardware tab with 'invalid shape'."""
    normalized = hardware.normalize(_with_repos(_REAL_REPOS))
    assert normalized["cpu"]["model"] == "Test CPU"


def test_the_full_inventory_still_shows_the_repos_objects():
    rows = hardware.full_inventory(_with_repos(_REAL_REPOS))
    assert any(r["group"] == "Repos" for r in rows)


@pytest.mark.parametrize("bad", [[None], ["just a string"], [[1, 2]], [[["deeper"]]]])
def test_anything_beyond_objects_and_lists_of_lines_is_still_rejected(bad):
    with pytest.raises(hardware.HardwareInventoryError, match="Repos section has an invalid shape"):
        hardware.normalize(_with_repos(bad))


def test_a_schema_section_may_never_contain_a_nested_list():
    raw = _valid_minimal_inxi()
    raw[2] = {"CPU": [{"model": "Test CPU", "cpus": 8}, ["stray"]]}
    with pytest.raises(hardware.HardwareInventoryError, match="CPU section has an invalid shape"):
        hardware.normalize(raw)
