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
