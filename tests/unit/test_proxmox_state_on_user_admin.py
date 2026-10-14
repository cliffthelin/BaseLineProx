"""Proxmox's own state lives on USER_ADMIN as overlay data, never on SUBSTRATE (operator 2026-10-14: "Proxmox has to use Overlay data like
everything else; it uses User_Admin to store its overlay"; DR257 step 2, DR259).

What is proved here is the wiring: which paths are redirected, and that every Proxmox service that reads them is ordered behind the
redirect service, so none of them can start on the bare substrate and build a second, empty configuration there. That a real Proxmox boots
with its configuration on USER_ADMIN is only provable in the rehearsal VM, and is recorded as such in DR259."""
import re
from pathlib import Path

import persist_bind_mounts as pbm

REPO = Path(__file__).resolve().parents[2]
PROXMOX_STATE = {
    "/var/lib/pve-cluster": "var-lib-pve-cluster",        # pmxcfs database: storage.cfg, user.cfg, datacenter.cfg, guests, certificates, TFA
    "/var/lib/pve-firewall": "var-lib-pve-firewall",
    "/var/lib/pve-manager": "var-lib-pve-manager",
    "/var/lib/rrdcached": "var-lib-rrdcached",
}
UNITS = ("pve-cluster", "pve-firewall", "pvedaemon", "pveproxy", "pvestatd", "rrdcached")


def test_every_proxmox_state_directory_is_redirected_to_its_own_subdirectory():
    for path, subdir in PROXMOX_STATE.items():
        assert pbm.REDIRECT_PATHS.get(path) == subdir, path


def test_subdirectories_stay_unique_and_the_earlier_redirects_remain():
    assert len(set(pbm.REDIRECT_PATHS.values())) == len(pbm.REDIRECT_PATHS)
    assert {"/etc/baseline", "/var/lib/baseline", "/var/log/baseline", "/root", "/home"} <= set(pbm.REDIRECT_PATHS)


def test_the_proxmox_state_is_whole_directories_never_single_files():
    # whole directories only: pmxcfs, rrdcached and the firewall replace files by rename, which a file bind mount would break
    for path in PROXMOX_STATE:
        assert not Path(path).suffix


def test_the_drop_in_orders_proxmox_after_the_redirects_and_refuses_to_start_without_them():
    text = (REPO / "boot/proxmox-overlay.conf").read_text()
    assert re.search(r"^\[Unit\]$", text, re.M)
    assert re.search(r"^Requires=baseline-persist-bind-mounts\.service$", text, re.M)
    assert re.search(r"^After=baseline-persist-bind-mounts\.service$", text, re.M)


def test_provisioning_installs_the_drop_in_for_every_proxmox_service_that_reads_the_state():
    script = (REPO / "boot/provision.sh").read_text()
    assert "boot/proxmox-overlay.conf" in script
    loop = next(line for line in script.splitlines() if line.startswith("for unit in") and "pve-cluster" in line)
    for unit in UNITS:
        assert unit in loop.replace(";", " ").split(), unit


def test_the_redirect_service_does_not_wait_for_proxmox_so_the_ordering_cannot_cycle():
    unit = (REPO / "boot/baseline-persist-bind-mounts.service").read_text()
    assert not re.search(r"(After|Requires|Wants)=.*pve", unit)
    for line in (REPO / "boot/baseline-persist-bind-mounts.service").read_text().splitlines():
        if line.startswith("Before="):
            assert "pve" not in line or "pve-cluster" in line     # being before Proxmox is the intent; never after it
