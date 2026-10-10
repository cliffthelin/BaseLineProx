"""Thin "is Proxmox already installed" gate.

Per direct user instruction (2026-09-23): Baseline does not need to
rebuild/reinstall Proxmox every time it runs. It needs a thin layer
that checks whether Proxmox is already present and, when it is, skips
straight to providing results (diagnostics) instead of invoking the
installer at all. The Milestone 1 install-pipeline work
(`drive_setup_install.py`, Gates A-F) is for *building a fresh disk
image* - a different job from this module, which is the check that
decides whether that job needs to run at all on a given target.

Known package absence, a missing `pveversion` command, and an unmounted
`/etc/pve` are normal fresh-host evidence. Probe failures remain errors;
they never authorize the installer path.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from repair import Runner


@dataclass
class InstallState:
    installed: bool
    version: str | None = None
    evidence: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class InstallDecision:
    action: str  # "run_diagnostics_only" | "run_installer" | "detection_unavailable"
    state: InstallState
    reason: str


def _probe(runner: Runner, argv: list[str], *, absent_markers=()):
    label = " ".join(argv)
    try:
        proc = runner.run(argv, timeout=10)
    except Exception as exc:  # command-boundary failures are observations, not absence
        return None, f"{label}: {type(exc).__name__}: {exc}"
    output = (proc.stdout or "").strip()
    detail = (proc.stderr or "").strip() or output or f"exited {proc.returncode}"
    if proc.returncode == 0:
        if output:
            return output, None
        return None, f"{label}: successful command returned no status"
    if any(marker in detail.lower() for marker in absent_markers):
        return None, None
    return None, f"{label}: {detail}"


def _dpkg_version(runner: Runner):
    return _probe(runner, ["dpkg-query", "-W", "-f=${Version}", "proxmox-ve"],
                  absent_markers=("no packages found",))


def _pveversion_present(runner: Runner):
    return _probe(runner, ["pveversion"],
                  absent_markers=("command not found", "not found on path",
                                  "no such file or directory"))


def detect_proxmox_install(runner: Runner) -> InstallState:
    """Checks three independent signals, in order of how authoritative
    they are - a package-manager record, the CLI tool it ships, and
    the cluster filesystem mountpoint it maintains. Any single
    positive signal is enough to call it installed; every signal
    absent (the common case on a genuinely fresh host, and in this
    project's own disposable QEMU test images) is a normal, expected
    "not installed" result, not an error."""
    evidence: list[str] = []
    errors: list[str] = []
    version: str | None = None

    dpkg_version, error = _dpkg_version(runner)
    if error:
        errors.append(error)
    if dpkg_version:
        evidence.append(f"dpkg-query reports proxmox-ve {dpkg_version} installed")
        version = dpkg_version

    pve_version_output, error = _pveversion_present(runner)
    if error:
        errors.append(error)
    if pve_version_output:
        evidence.append(f"pveversion runs and reports: {pve_version_output}")
        if version is None:
            version = pve_version_output

    try:
        pmxcfs_mounted = runner.path_exists("/etc/pve")
    except Exception as exc:
        errors.append(f"/etc/pve mountpoint: {type(exc).__name__}: {exc}")
    else:
        if pmxcfs_mounted:
            evidence.append("/etc/pve (pmxcfs) is present")

    return InstallState(installed=bool(evidence), version=version,
                        evidence=evidence, errors=errors)


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
    if state.errors:
        return InstallDecision(
            action="detection_unavailable",
            state=state,
            reason="Proxmox installation status could not be established: " + "; ".join(state.errors),
        )
    return InstallDecision(
        action="run_installer",
        state=state,
        reason="No installed-Proxmox evidence found on this target - the installer path is next.",
    )


def check(runner: Runner) -> InstallDecision:
    """Convenience entry point: detect, then decide, in one call."""
    return decide_next_action(detect_proxmox_install(runner))
