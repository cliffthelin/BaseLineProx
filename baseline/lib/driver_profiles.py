"""Driver and firmware support for the machines this product is run on (DR262).

One table says which Debian 13 package a piece of hardware needs. Every package name below was checked against Debian 13's own file index
(`dists/trixie/*/Contents-all`) by the firmware file the kernel driver asks for, not taken from memory:

  mediatek/WIFI_RAM_CODE_MT7961_1.bin, BT_RAM_CODE_MT7961_1_2_hdr.bin   -> firmware-mediatek       (MT7921K Wi-Fi 6E and its Bluetooth)
  iwlwifi-8265-*.ucode, intel/ibt-12-16.sfi                             -> firmware-iwlwifi        (Intel Wireless-AC 8265 and its Bluetooth)
  i915/kbl_dmc_ver1_04.bin, kbl_guc_*, kbl_huc_*                        -> firmware-intel-graphics (Kaby Lake graphics)
  /lib/firmware/regulatory.db                                            -> wireless-regdb          (any Wi-Fi; the Latitude's journal shows it missing)
  CPU microcode                                                          -> amd64-microcode / intel-microcode

Detection reads what the machine reports (`lspci -nn`, `lsusb`, the CPU vendor), so a package is recommended for hardware that is there and never for hardware
that is not. The two named machines are what the installer cache is built to cover; the Latitude's list is partly from its journal and Dell's published
configuration and says so (`confirmed`): run `baseline-drivers` on the laptop to settle it.
"""
from __future__ import annotations

import re

PACKAGES = {
    "amd64-microcode": "AMD CPU microcode",
    "intel-microcode": "Intel CPU microcode",
    "firmware-mediatek": "MediaTek Wi-Fi and Bluetooth firmware",
    "firmware-realtek": "Realtek network firmware",
    "firmware-iwlwifi": "Intel Wi-Fi and Bluetooth firmware",
    "firmware-intel-graphics": "Intel graphics firmware",
    "wireless-regdb": "Wi-Fi regulatory database",
}
_PCI = re.compile(r"^\S+\s+(?P<cls>[^\[]+)\[(?P<class_id>[0-9a-f]{4})\]:\s+(?P<name>.*)\[(?P<vendor>[0-9a-f]{4}):(?P<device>[0-9a-f]{4})\]")
_USB = re.compile(r"ID (?P<vendor>[0-9a-f]{4}):(?P<device>[0-9a-f]{4})\s*(?P<name>.*)")

PROFILES = {
    "asus-desktop": {
        "name": "This development machine (ASUS desktop: Ryzen 9 7900X, RTX 3070 and Tesla P40, Intel I225-V, MediaTek MT7921K Wi-Fi)",
        "packages": ("amd64-microcode", "firmware-mediatek", "wireless-regdb"),
        "confirmed": True,
        "notes": "Read from its own lspci/lsusb. The Intel I225-V (igc) and the NVMe drives need no firmware package. The NVIDIA GPUs need no firmware from Debian's "
                 "non-free-firmware archive either; a host driver for them is a separate, deliberate choice (the cards are for passthrough to a VM), not carried here.",
    },
    "dell-latitude-5290": {
        "name": "Dell Latitude 5290 (the test laptop)",
        "packages": ("intel-microcode", "firmware-iwlwifi", "firmware-intel-graphics", "wireless-regdb"),
        "confirmed": False,
        "notes": "From the laptop's journal (i915 graphics, an Intel Bluetooth controller, and `regulatory.db` failing to load) and Dell's published configuration (Intel "
                 "Wireless-AC 8265 with Bluetooth). Not read from the machine: run `baseline-drivers` on it. Its LTE modem needs no firmware package (ModemManager and "
                 "the kernel's QMI/MBIM drivers handle it).",
    },
}


def parse_pci(text: str) -> list:
    rows = []
    for line in text.splitlines():
        match = _PCI.match(line)
        if match:
            rows.append({"class_id": match["class_id"], "name": match["name"].strip(), "vendor": match["vendor"], "device": match["device"]})
    return rows


def parse_usb(text: str) -> list:
    return [{"vendor": m["vendor"], "device": m["device"], "name": m["name"].strip()} for line in text.splitlines() if (m := _USB.search(line))]


def cpu_vendor(cpuinfo: str) -> str:
    for line in cpuinfo.splitlines():
        if line.startswith("vendor_id"):
            return line.split(":", 1)[1].strip()
    return ""


def needed(pci_text: str = "", usb_text: str = "", cpuinfo: str = "") -> list:
    """[{package, label, why}] for the hardware reported, in a stable order. Nothing is recommended for hardware that is not there."""
    found: dict = {}

    def want(package: str, why: str):
        found.setdefault(package, {"package": package, "label": PACKAGES[package], "why": []})["why"].append(why)

    vendor = cpu_vendor(cpuinfo)
    if vendor == "AuthenticAMD":
        want("amd64-microcode", "AMD processor")
    elif vendor == "GenuineIntel":
        want("intel-microcode", "Intel processor")
    wireless = False
    for dev in parse_pci(pci_text):
        name = f"{dev['name']} ({dev['vendor']}:{dev['device']})"
        if dev["class_id"] == "0280":                      # network controller: wireless
            wireless = True
            want({"8086": "firmware-iwlwifi", "14c3": "firmware-mediatek", "10ec": "firmware-realtek"}.get(dev["vendor"], "wireless-regdb"), name)
        elif dev["class_id"] == "0200" and dev["vendor"] == "10ec":
            want("firmware-realtek", name)
        elif dev["class_id"] in ("0300", "0302", "0380") and dev["vendor"] == "8086":
            want("firmware-intel-graphics", name)
    for dev in parse_usb(usb_text):
        name = f"{dev['name']} ({dev['vendor']}:{dev['device']})"
        if dev["vendor"] == "8087":                        # Intel's Bluetooth controllers load their firmware from firmware-iwlwifi
            want("firmware-iwlwifi", name)
        elif dev["vendor"] == "0e8d":                      # MediaTek wireless/Bluetooth
            wireless = True
            want("firmware-mediatek", name)
    if wireless:
        want("wireless-regdb", "a Wi-Fi device needs the regulatory database")
    return sorted(found.values(), key=lambda item: list(PACKAGES).index(item["package"]))


def carried_packages() -> tuple:
    """Every package the installer cache must carry so both named machines work with no internet, in a stable order, plus the generic Wi-Fi and
    Realtek ones the catalog always carried."""
    wanted = {"firmware-realtek"}
    for profile in PROFILES.values():
        wanted.update(profile["packages"])
    return tuple(p for p in PACKAGES if p in wanted)
