"""Bluetooth and sound must be on the drive when it is built offline (operator, 2026-10-14: the GUI needs Bluetooth for mouse, keyboard,
audio, data transfer and tether). They used to be installed only once the machine first reached the internet, so a drive that never did had
none. provision.sh now installs them from the carried repository, and the carried list is read from provision.sh."""
from pathlib import Path

import harness_install
import offline_cache

REPO = Path(__file__).resolve().parents[2]


def test_provision_installs_the_sound_and_bluetooth_packages_the_audio_page_needs():
    names = offline_cache.provision_packages((REPO / "boot/provision.sh").read_text())
    for package in harness_install.APT_PACKAGES:
        assert package in names, f"{package} is not installed by provision.sh, so a drive built offline would not have it"


def test_they_are_carried_in_the_offline_repository_too():
    carried = offline_cache.required_packages(REPO)
    for package in harness_install.APT_PACKAGES:
        assert package in carried
