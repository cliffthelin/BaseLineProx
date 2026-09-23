"""Thin "is Proxmox already installed" gate.

Per direct user instruction (2026-09-23): Baseline does not need to
rebuild/reinstall Proxmox every time it runs. It needs a thin layer
that checks whether Proxmox is already present and, when it is, skips
straight to providing results (diagnostics) instead of invoking the
installer at all. The Milestone 1 install-pipeline work
(`drive_setup_install.py`, Gates A-F) is for *building a fresh disk
image* - a different job from this module, which is the check that
decides whether that job needs to run at all on a given target.

Never raises on an absent tool/path - a host with no Proxmox installed
at all is the normal "go ahead and install" case, not an error.
Reuses `repair.py`'s `Runner`/`RealRunner`/`FakeRunner` pattern rather
than inventing a new subprocess boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:  # minimal shape match for standalone use/testing
        def run(self, argv, timeout=10):
            raise NotImplementedError

        def path_exists(self, path):
            raise NotImplementedError


@dataclass
class InstallState:
    installed: bool
    version: str | None = None
    evidence: list[str] = field(default_factory=list)


@dataclass
class InstallDecision:
    action: str  # "run_diagnostics_only" | "run_installer"
    state: InstallState
    reason: str


def _dpkg_version(runner: Runner) -> str | None:
    proc = runner.run(["dpkg-query", "-W", "-f=${Version}", "proxmox-ve"], timeout=10)
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    return None


def _pveversion_present(runner: Runner) -> str | None:
    proc = runner.run(["pveversion"], timeout=10)
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    return None


def _pmxcfs_mounted(runner: Runner) -> bool:
    return runner.path_exists("/etc/pve")


def detect_proxmox_install(runner: Runner) -> InstallState:
    """Checks three independent signals, in order of how authoritative
    they are - a package-manager record, the CLI tool it ships, and
    the cluster filesystem mountpoint it maintains. Any single
    positive signal is enough to call it installed; every signal
    absent (the common case on a genuinely fresh host, and in this
    project's own disposable QEMU test images) is a normal, expected
    "not installed" result, not an error."""
    evidence: list[str] = []
    version: str | None = None

    dpkg_version = _dpkg_version(runner)
    if dpkg_version:
        evidence.append(f"dpkg-query reports proxmox-ve {dpkg_version} installed")
        version = dpkg_version

    pve_version_output = _pveversion_present(runner)
    if pve_version_output:
        evidence.append(f"pveversion runs and reports: {pve_version_output}")
        if version is None:
            version = pve_version_output

    if _pmxcfs_mounted(runner):
        evidence.append("/etc/pve (pmxcfs) is present")

    return InstallState(installed=bool(evidence), version=version, evidence=evidence)


def decide_next_action(state: InstallState) -> InstallDecision:
    """The actual gate: already installed -> go straight to providing
    results (diagnostics), never re-invoke the installer. Not
    installed -> the installer path is the correct next step."""
    if state.installed:
        return InstallDecision(
            action="run_diagnostics_only",
            state=state,
            reason="Proxmox is already installed (" + "; ".join(state.evidence) +
                   ") - skipping the installer entirely and going straight to results.",
        )
    return InstallDecision(
        action="run_installer",
        state=state,
        reason="No installed-Proxmox evidence found on this target - the installer path is next.",
    )


def check(runner: Runner) -> InstallDecision:
    """Convenience entry point: detect, then decide, in one call."""
    return decide_next_action(detect_proxmox_install(runner))
