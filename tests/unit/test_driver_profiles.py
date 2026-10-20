"""Driver support for the two named machines (DR262): detection from what a machine reports, and the carried set that covers both."""
from pathlib import Path

import driver_profiles as dp
import installer_cache as ic

# This development machine's own `lspci -nn` and `lsusb` (device ids only), as captured on 2026-10-16.
ASUS_PCI = """01:00.0 VGA compatible controller [0300]: NVIDIA Corporation GA104 [GeForce RTX 3070] [10de:2484] (rev a1)
02:00.0 Non-Volatile memory controller [0108]: Phison Electronics Corporation PS5013-E13 PCIe3 NVMe Controller (DRAM-less) [1987:5013] (rev 01)
05:00.0 3D controller [0302]: NVIDIA Corporation GP102GL [Tesla P40] [10de:1b38] (rev a1)
08:00.0 Ethernet controller [0200]: Intel Corporation Ethernet Controller I225-V [8086:15f3] (rev 03)
09:00.0 Network controller [0280]: MEDIATEK Corp. MT7921K (RZ608) Wi-Fi 6E 80MHz [14c3:0608]
"""
ASUS_USB = "Bus 001 Device 015: ID 0e8d:0608 MediaTek Inc. Wireless_Device\nBus 001 Device 003: ID 0b05:1a52 ASUSTek Computer, Inc. USB Audio\n"
LATITUDE_PCI = """00:02.0 VGA compatible controller [0300]: Intel Corporation UHD Graphics 620 [8086:5917] (rev 07)
02:00.0 Network controller [0280]: Intel Corporation Wireless 8265 / 8275 [8086:24fd] (rev 78)
"""
LATITUDE_USB = "Bus 001 Device 004: ID 8087:0a2b Intel Corp. Bluetooth wireless interface\n"


def names(rows):
    return [r["package"] for r in rows]


def test_this_machine_needs_amd_microcode_mediatek_firmware_and_the_regulatory_database_and_nothing_for_nvidia_intel_nic_or_nvme():
    rows = dp.needed(ASUS_PCI, ASUS_USB, "vendor_id\t: AuthenticAMD\n")
    assert names(rows) == ["amd64-microcode", "firmware-mediatek", "wireless-regdb"]


def test_the_latitude_profile_needs_intel_firmware_graphics_firmware_and_the_regulatory_database():
    rows = dp.needed(LATITUDE_PCI, LATITUDE_USB, "vendor_id\t: GenuineIntel\n")
    assert names(rows) == ["intel-microcode", "firmware-iwlwifi", "firmware-intel-graphics", "wireless-regdb"]
    assert any("Bluetooth" in why for why in next(r for r in rows if r["package"] == "firmware-iwlwifi")["why"])


def test_nothing_is_recommended_for_hardware_that_is_not_there():
    assert dp.needed("", "", "") == []
    assert "firmware-iwlwifi" not in names(dp.needed(ASUS_PCI, ASUS_USB, "vendor_id\t: AuthenticAMD\n"))
    assert "intel-microcode" not in names(dp.needed(ASUS_PCI, ASUS_USB, "vendor_id\t: AuthenticAMD\n"))


def test_the_named_profiles_are_covered_by_what_detection_recommends_for_their_hardware():
    asus = set(names(dp.needed(ASUS_PCI, ASUS_USB, "vendor_id\t: AuthenticAMD\n")))
    latitude = set(names(dp.needed(LATITUDE_PCI, LATITUDE_USB, "vendor_id\t: GenuineIntel\n")))
    assert asus == set(dp.PROFILES["asus-desktop"]["packages"]) and latitude == set(dp.PROFILES["dell-latitude-5290"]["packages"])


def test_the_installer_cache_carries_every_package_either_machine_needs():
    assert set(dp.carried_packages()) == set(ic.firmware_packages())
    for profile in dp.PROFILES.values():
        assert set(profile["packages"]) <= set(ic.firmware_packages())
    assert set(ic.firmware_packages()) <= set(dp.PACKAGES)


def test_only_the_machine_that_was_read_is_marked_confirmed():
    assert dp.PROFILES["asus-desktop"]["confirmed"] is True and dp.PROFILES["dell-latitude-5290"]["confirmed"] is False


def test_the_cli_reports_not_applicable_off_debian_instead_of_calling_firmware_missing():
    text = (Path(__file__).resolve().parents[2] / "baseline/bin/baseline-drivers").read_text()
    assert "not Debian" in text and '== "debian"' in text and "ID_LIKE" not in text


def test_provision_stages_the_driver_tool_and_the_modules_it_and_the_launcher_need():
    provision = (Path(__file__).resolve().parents[2] / "boot/provision.sh").read_text()
    for staged in ("baseline/lib/driver_profiles.py", "baseline/bin/baseline-drivers", "baseline/lib/os_profiles.py", "baseline/lib/os_list.py"):
        assert f'"$SRC/{staged}"' in provision
