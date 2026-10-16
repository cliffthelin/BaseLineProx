"""Baseline's boot units and Proxmox's own must not contain an ordering cycle (found 2026-10-15 in the QEMU rehearsal).

DR259 ordered every Proxmox service after `baseline-persist-bind-mounts.service`, but `baseline-storage-verify.service` was already
ordered after `pve-cluster.service` and before the redirects. systemd resolved the loop by deleting the redirect service's start job: Proxmox
did not start and the first-boot CONFIRM screen never appeared. No unit test saw it, because the cycle is only visible when the units
are loaded together. This loads them together and asks systemd (`systemd-analyze verify`), with Proxmox's real ordering directives
(tests/fixtures/proxmox-units) and the drop-ins exactly as provision.sh installs them."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PROVISION = (REPO / "boot/provision.sh").read_text()

pytestmark = pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="systemd-analyze is not installed")


def _dropins_from_provision() -> dict:
    """{unit: {file: text}} for the drop-ins provision.sh writes into /etc/systemd/system/<unit>.d/."""
    found = {}
    gate = re.search(r"for storage_unit in ([^;]+); do.*?<<'STORAGE_GATE'\n(.*?)\nSTORAGE_GATE", PROVISION, re.S)
    for unit in gate.group(1).split():
        found.setdefault(unit.removesuffix(".service"), {})["storage.conf"] = gate.group(2) + "\n"
    reconcile = re.search(r"for reconcile_unit in ([^;]+); do.*?<<'RECONCILE_GATE'\n(.*?)\nRECONCILE_GATE", PROVISION, re.S)
    for unit in reconcile.group(1).split():
        found.setdefault(unit.removesuffix(".service"), {})["reconcile.conf"] = reconcile.group(2) + "\n"
    overlay = re.search(r"for unit in ([^;]+); do\n\s+mkdir -p \"/etc/systemd/system/\$unit\.service\.d\"\n\s+cp \"\$SRC/boot/proxmox-overlay\.conf\"", PROVISION)
    for unit in overlay.group(1).split():
        found.setdefault(unit, {})["baseline-overlay.conf"] = (REPO / "boot/proxmox-overlay.conf").read_text()
    return found


def _build_unit_tree(root: Path) -> None:
    sources = list((REPO / "tests/fixtures/proxmox-units").glob("*.service")) + \
        [p for p in (REPO / "boot").iterdir() if p.suffix in (".service", ".timer")]
    wants = root / "multi-user.target.wants"
    wants.mkdir()
    for path in sources:
        shutil.copy(path, root / path.name)
        if re.search(r"^WantedBy=.*multi-user\.target", path.read_text(), re.M):
            os.symlink(f"../{path.name}", wants / path.name)
    for unit, files in _dropins_from_provision().items():
        folder = root / f"{unit}.service.d"
        folder.mkdir(exist_ok=True)
        for name, text in files.items():
            (folder / name).write_text(text)


def _analyze(tmp_path: Path) -> str:
    _build_unit_tree(tmp_path)
    env = {**os.environ, "SYSTEMD_UNIT_PATH": f"{tmp_path}:"}
    done = subprocess.run(["systemd-analyze", "verify", "--man=no", "multi-user.target"], env=env, capture_output=True, text=True, timeout=60)
    return done.stdout + done.stderr


def test_the_dropins_provision_installs_are_found_so_the_check_is_not_vacuous():
    found = _dropins_from_provision()
    assert {"baseline-persist-bind-mounts", "baseline-firstboot", "baseline-kiosk"} <= set(found)
    assert {"pve-cluster", "pveproxy", "rrdcached"} <= set(found)
    assert "After=baseline-persist-bind-mounts.service" in found["pve-cluster"]["baseline-overlay.conf"]


def test_baseline_and_proxmox_units_together_have_no_ordering_cycle(tmp_path):
    report = _analyze(tmp_path)
    assert "unrecognized option" not in report and "Failed to" not in report, "the analyzer itself did not run:\n" + report
    cycle = [line for line in report.splitlines() if "ordering cycle" in line or "Found dependency" in line or "deleted to break" in line]
    assert cycle == [], "systemd found an ordering cycle:\n" + "\n".join(cycle)
