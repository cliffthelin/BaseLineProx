"""First-boot state machine (Gate E) - the real, integrated authorization
path connecting the already-proven pieces rather than repeating them:

  - `proxmox_detect.py`  - informational: confirms Proxmox is already
    installed (never re-invokes the installer).
  - `firstboot_network_repair.py` - discovery, exact-diff diagnosis, and
    the real apply/verify calls into `repair.py`/`repair_additive.py`
    (Gate A). This module calls its public building blocks directly
    (`discover`, `diagnose`, `wait_for_confirmation`) rather than its
    all-in-one wrapper, so a single combined tty1 screen and a single
    CONFIRM gate can cover network repair AND package installation
    together - not two separate prompts for one first boot.
  - `setup_intent.py` - informational integrity status only, displayed
    on tty1. NEVER the authorization gate: a colocated verification key
    is an integrity/corruption check, not authentication (PRD SS5.6),
    and no signed intent is wired into this flow's actual decision at
    all. The literal CONFIRM keystroke is the only thing that
    authorizes anything here.
  - `diagnostics.py` - functional verification of the five installed
    diagnostic tools after installation (hardware absence is a normal,
    expected result per decision record 22 - not a verification
    failure; a collector raising or the tool being uninvokable would
    be).

States, each durably journaled (fsync file + fsync containing directory
+ atomic rename - the same pattern `setup_intent.record_consumption`
already uses) before the next stage begins:

  created -> detected -> discovered -> proposed -> confirmed
  -> network_repaired -> packages_installed -> packages_verified
  -> committed

  confirmed -> network_repair_failed  (terminal, unless the drive carries
                                       its own verified package repository)
  network_repair_failed -> packages_installed (package_source="offline")
  -> packages_verified -> committed (network_verified=False)

`network_repaired` is a success-only state: it is entered if and only if
the repair applied AND independently verified (or the lifeline was
already healthy). A refused or failed repair is recorded as the
distinct `network_repair_failed` state instead of `network_repaired`
with a false outcome flag - a state named "repaired" must never mean
"not repaired". `record_transition` enforces this as a hard invariant,
not just a convention, and not just by rejecting an explicit False:
writing `network_repaired` requires ALL of `network_ok is True`
(exactly - omitted, `None`, or any other value is refused identically
to an explicit `False`), a non-empty `target_interface`, and a
non-empty `verification` dict whose every value is exactly `True` -
see `_require_genuine_network_repaired_evidence`. The evidence is
never fabricated: `RepairResult.verification` (repair.py/
repair_additive.py) is populated only from checks the repair pipeline
itself genuinely ran and passed, and the already-healthy path reuses
`firstboot_network_repair.facts_verification`'s real address/gateway
facts rather than inventing them. Recovery branches on which of the
two states is recorded, never by inferring success from a shared
phase name.

Gating, exactly as specified:
  - A broken lifeline with no safe repair candidate refuses outright -
    no proposal, no package install.
  - The combined proposal (Proxmox detection + network diff-or-healthy
    + the five proposed packages + rollback/verify description +
    setup-intent status) is shown, then this blocks indefinitely for
    the literal string CONFIRM - no timeout, no default, EOF never
    confirms (identical discipline to `wait_for_confirmation`, reused
    unchanged, not reimplemented).
  - Package installation is refused unless network repair (or an
    already-healthy lifeline) is confirmed AND independently verified -
    with one exception, added 2026-10-10 for the self-contained
    installer: when networking did not verify but this drive carries its
    own package repository, registered with apt and re-verified against
    its manifest at that moment (`offline_repository`), the tools are
    installed from that repository ONLY (`install_diagnostic_tools`
    restricts apt to that one source list, so no network source is ever
    consulted). The network failure is not overwritten: it stays in the
    journal as `network_repair_failed`, and `committed` records
    `network_verified=False` and `package_source="offline"`. Without a
    verified repository the old refusal applies unchanged. This does not
    widen consent: it runs only after CONFIRM, whose screen names the
    offline source whenever one is present.
  - The durable completion marker is written ONLY after package
    installation AND functional verification both succeed - never on
    confirmation alone, never on network success alone.

A corrupted or unparseable journal is never trusted for resume - fail
closed by starting over from `created`. Every state through `confirmed`
is safe to redo (read-only discovery, or a fresh required CONFIRM);
this can only ever cause a redundant discovery or an extra
confirmation, never a skipped authorization.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path

import config_pipeline
import diagnostics
import firstboot_network_repair as fbnr
import network
import proxmox_detect
import repair
import repair_additive

# Fallback only when no network_repaired evidence exists yet in the
# journal (e.g. the very first run, before network repair has landed) -
# this project's own real, detected default wired NIC (lspci -k, this
# session) is eno1; config_pipeline's ethtool step is a no-op anyway
# unless the exported config actually carries ethtool_* keys.
_DEFAULT_NETWORK_INTERFACE = "eno1"

STATE_DIR = Path("/var/lib/baseline-firstboot")

STATES = ["created", "detected", "discovered", "proposed", "confirmed",
          "network_repaired", "network_repair_failed",
          "packages_installed", "packages_verified", "committed"]

DIAGNOSTIC_PACKAGES = ["lm-sensors", "nvme-cli", "smartmontools", "iperf3", "ethtool"]

# The drive's own package repository, carried by the self-contained installer
# (baseline-first-boot-install's `installer` step) and registered as a
# permanent apt source by its `provision` step.
OFFLINE_REPOSITORY = Path("/mnt/INSTALLER_CACHE/installer/expanded/baseline-cache")
OFFLINE_SOURCES = Path("/etc/apt/sources.list.d/baseline-installer-cache.list")


# ---------------------------------------------------------------------------
# Durable journal / completion marker - same proven pattern throughout.
# ---------------------------------------------------------------------------

def _durable_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".tmp-{secrets.token_hex(8)}"
    with open(tmp, "w") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    dir_fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _journal_path(state_dir: Path) -> Path:
    return state_dir / "journal.json"


def _marker_path(state_dir: Path) -> Path:
    return state_dir / "complete"


def already_completed(state_dir: Path = STATE_DIR) -> str | None:
    """Checked first, before any discovery or side effect - even a
    maliciously or accidentally re-triggered service start cannot
    cause work to redo past a real prior commit. Existence-based, not
    content-based - matches `setup_intent.is_consumed`'s fail-closed
    discipline exactly."""
    marker = _marker_path(state_dir)
    return marker.read_text().strip() if marker.exists() else None


def mark_complete(state_dir: Path = STATE_DIR) -> None:
    _durable_write(_marker_path(state_dir), time.strftime("%Y-%m-%dT%H:%M:%S") + "\n")


def load_journal(state_dir: Path = STATE_DIR) -> dict:
    path = _journal_path(state_dir)
    if not path.exists():
        return {"state": "new", "history": []}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or "state" not in data or data["state"] not in STATES + ["new"]:
            raise ValueError("malformed journal")
        return data
    except (json.JSONDecodeError, ValueError, OSError):
        # Fail-closed: never resume into a consequential state from a
        # journal we can't trust. Starting over from "created" is
        # always safe - see module docstring.
        return {"state": "new", "history": [], "journal_was_corrupted": True}


def _require_genuine_network_repaired_evidence(detail: dict) -> None:
    """Enforced on every attempt to write the 'network_repaired' state -
    never bypassable by a caller forgetting a keyword. A state named
    "repaired" must never be enterable on the mere absence of an
    explicit network_ok=False; it must carry its own positive proof:

      - network_ok must be exactly True (not merely not-False; a caller
        that forgets to pass it at all is refused just as loudly as one
        that passes False, None, or a truthy-but-wrong value).
      - target_interface must be a genuine, non-empty interface name.
      - verification must be a non-empty dict whose every value is
        exactly True - no False, no None, no truthy strings, no empty
        dict. Each key reflects a check that pipeline genuinely ran and
        passed (see RepairResult.verification's docstring) - the set of
        keys is allowed to vary by repair mode (replace-mode only ever
        checks address/gateway today; additive-mode also checks
        dns/https), but every value present must be real and positive.
    """
    if detail.get("network_ok") is not True:
        raise ValueError(
            "invariant violation: 'network_repaired' requires network_ok=True explicitly - "
            "a refused, failed, or omitted-outcome repair belongs in the "
            "'network_repair_failed' state instead")
    if not detail.get("target_interface"):
        raise ValueError(
            "invariant violation: 'network_repaired' requires a genuine, non-empty "
            "target_interface - the interface this verification evidence is bound to")
    verification = detail.get("verification")
    if not isinstance(verification, dict) or not verification:
        raise ValueError(
            "invariant violation: 'network_repaired' requires non-empty explicit "
            "target-bound verification evidence (a 'verification' dict) - not merely "
            "the absence of network_ok=False")
    if not all(v is True for v in verification.values()):
        raise ValueError(
            "invariant violation: 'network_repaired' requires every verification check "
            "to be exactly True - a False, None, or otherwise malformed value means the "
            "repair was not genuinely verified")


def record_transition(state_dir: Path, journal: dict, state: str, **detail) -> dict:
    assert state in STATES, f"unknown state {state!r}"
    if state == "network_repaired":
        _require_genuine_network_repaired_evidence(detail)
    entry = {"state": state, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **detail}
    new_journal = {"state": state, "history": journal.get("history", []) + [entry]}
    _durable_write(_journal_path(state_dir), json.dumps(new_journal, indent=2, default=str))
    return new_journal


def _last(journal: dict, state: str) -> dict:
    return next(e for e in reversed(journal["history"]) if e["state"] == state)


# ---------------------------------------------------------------------------
# Package install / functional verification for the five diagnostic tools.
# ---------------------------------------------------------------------------

def offline_repository(root: Path = OFFLINE_REPOSITORY, sources: Path = OFFLINE_SOURCES) -> dict:
    """Is this drive's own package repository present, registered with apt,
    and intact? Intact means every carried file re-hashes to its manifest
    entry right now - presence alone is not trusted. Never raises."""
    import offline_cache
    facts = {"available": False, "root": str(root), "sources": str(sources), "files_verified": 0, "reason": ""}
    if not sources.is_file():
        return dict(facts, reason=f"no apt source registered at {sources}")
    if not (root / "apt" / "Packages").is_file():
        return dict(facts, reason=f"no package index at {root / 'apt' / 'Packages'}")
    try:
        manifest = json.loads((root / "MANIFEST.json").read_text())
        count = offline_cache.verify_manifest(root, manifest)
    except (OSError, ValueError, RuntimeError) as exc:
        return dict(facts, reason=f"repository does not verify: {exc}")
    return dict(facts, available=True, files_verified=count)


def install_diagnostic_tools(runner: repair.Runner, *, offline_sources: Path | None = None) -> dict:
    """With `offline_sources`, apt uses that one source list and nothing else:
    no network source is consulted at all, so a broken or half-working
    network can neither be used nor hang the install on DNS."""
    env = ["env", "DEBIAN_FRONTEND=noninteractive"]
    only = []
    if offline_sources is not None:
        only = ["-o", f"Dir::Etc::SourceList={offline_sources}", "-o", "Dir::Etc::SourceParts=-",
                "-o", "Acquire::Languages=none"]
        update = runner.run(env + ["apt-get"] + only + ["update"], timeout=300)
        if update.returncode != 0:
            tail = (update.stderr or update.stdout or "")[-2000:]
            return {"ok": False, "returncode": update.returncode, "detail": "offline index update failed: " + tail}
    proc = runner.run(env + ["apt-get"] + only + ["install", "-y"] + DIAGNOSTIC_PACKAGES, timeout=300)
    ok = proc.returncode == 0
    tail = (proc.stdout if ok else (proc.stderr or proc.stdout)) or ""
    return {"ok": ok, "returncode": proc.returncode, "detail": tail[-2000:]}


def verify_diagnostic_tools(runner: repair.Runner) -> dict:
    """Package presence + iperf3 safety + a real functional pass through
    diagnostics.py's own collectors. Hardware absence is a normal,
    expected result on a VM (decision record 22) - only a missing
    package or an unsafe iperf3 state fails this check."""
    dpkg_proc = runner.run(
        ["dpkg-query", "-W", "-f=${Package} ${Status}\n"] + DIAGNOSTIC_PACKAGES, timeout=15)
    installed = {}
    for line in dpkg_proc.stdout.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2:
            installed[parts[0]] = "install ok installed" in parts[1]
    all_installed = all(installed.get(p, False) for p in DIAGNOSTIC_PACKAGES)

    iperf_enabled = runner.run(["systemctl", "is-enabled", "iperf3"], timeout=10).stdout.strip()
    iperf_active = runner.run(["systemctl", "is-active", "iperf3"], timeout=10).stdout.strip()
    listen_proc = runner.run(["ss", "-tln"], timeout=10)
    iperf_listening = any(":5201" in line for line in listen_proc.stdout.splitlines())
    iperf_safe = (iperf_enabled == "disabled" and iperf_active != "active" and not iperf_listening)

    functional = {
        "lm-sensors": diagnostics.collect_sensors(runner).__dict__,
        "nvme-cli": diagnostics.collect_nvme(runner).__dict__,
        "smartmontools": diagnostics.collect_smart(runner).__dict__,
        "ethtool": diagnostics.collect_ethtool(runner, network.list_interfaces).__dict__,
    }

    ok = all_installed and iperf_safe
    reason = "" if ok else ("missing package(s): " + ", ".join(p for p in DIAGNOSTIC_PACKAGES if not installed.get(p))
                             if not all_installed else f"iperf3 not safe: enabled={iperf_enabled} active={iperf_active} listening={iperf_listening}")
    return {"ok": ok, "reason": reason, "installed": installed, "iperf3_enabled": iperf_enabled,
            "iperf3_active": iperf_active, "iperf3_listening": iperf_listening,
            "iperf3_safe": iperf_safe, "functional": functional}


def proxmox_detection_block(entry: dict) -> dict | None:
    """Return a fail-closed firstboot result when absence is unproven."""
    errors = entry.get("proxmox_probe_errors") or []
    if entry.get("proxmox_installed") or not errors:
        return None
    return {"action": "detection_unavailable", "reason": "; ".join(errors),
            "package_install_allowed": False}


# ---------------------------------------------------------------------------
# Combined tty1 proposal - everything the operator needs to authorize in
# one screen, per Gate E's requirement.
# ---------------------------------------------------------------------------

def format_setup_intent_status() -> str:
    """Informational only - see module docstring. Never the gate."""
    return (
        "REAL-012: setup-intent staging inspection is unavailable; staged state is unknown.\n"
        "Where a colocated verification key is used elsewhere in this project,\n"
        "it is an INTEGRITY/CORRUPTION check only, per PRD SS5.6 - it is not\n"
        "authentication, and it is never the authorization gate for this\n"
        "action. Only a real CONFIRM keystroke, read below, authorizes anything."
    )


def format_full_proposal(detection, discovery: dict, diagnosis: dict, *, offline_available: bool = False) -> str:
    lines = ["=" * 64, "Baseline first-boot: detected state and proposed actions", ""]

    lines.append(f"Proxmox installation: {'DETECTED' if detection.installed else 'NOT DETECTED'}")
    for e in detection.evidence:
        lines.append(f"  - {e}")
    lines.append("")

    if diagnosis["needs_repair"]:
        network_lines = fbnr.format_proposal_for_tty1(diagnosis).splitlines()
        # Drop that function's own trailing CONFIRM prompt/border - this
        # screen has exactly one combined prompt at the very end instead.
        network_lines = network_lines[2:-3]
        lines.extend(network_lines)
    else:
        lines.append("Network: lifeline already healthy - no repair needed.")
    lines.append("")

    if offline_available:
        lines.append("Diagnostic tools proposed for installation (after network verifies, or, if it")
        lines.append("does not, from this drive's own verified package repository - never the network):")
    else:
        lines.append("Diagnostic tools proposed for installation (only after network verifies):")
    for pkg in DIAGNOSTIC_PACKAGES:
        lines.append(f"  - {pkg}")
    lines.append("")

    lines.append("Rollback and verification:")
    lines.append("  An independent rollback timer is armed BEFORE any network write.")
    lines.append("  Address, target-bound route/gateway, DNS, and HTTPS are independently")
    if offline_available:
        lines.append("  re-verified after. If that verification fails, the failure is recorded")
        lines.append("  and the tools come from this drive's repository only, re-checked against")
        lines.append("  its manifest first. The completion marker is written only after package")
        lines.append("  installation AND functional verification both succeed.")
    else:
        lines.append("  re-verified after. Package installation is refused unless that")
        lines.append("  verification succeeds; the completion marker is written only after")
        lines.append("  package installation AND functional verification both succeed.")
    lines.append("")

    lines.append(format_setup_intent_status())
    lines.append("")
    lines.append("Type CONFIRM and press Enter to proceed. No timeout. No default.")
    lines.append("=" * 64)
    return "\n".join(lines)


def print_tty1(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Configurator wiring - applies whatever the operator exported from the
# Baseline Install Configurator artifact and placed on this disk, via
# config_pipeline.py's already-real apply functions. Best-effort and
# non-gating by design: an operator who never exported a config gets
# `None` back from load_config and every subsystem is simply skipped -
# this must never block or fail the network-repair/package-install flow
# above, which is the one gate that actually matters. Runs post-install
# only, against this live installed system - never touches an ISO.
# ---------------------------------------------------------------------------

def _resolve_network_interface(journal: dict) -> str:
    try:
        return _last(journal, "network_repaired")["target_interface"] or _DEFAULT_NETWORK_INTERFACE
    except StopIteration:
        return _DEFAULT_NETWORK_INTERFACE


def apply_configurator_settings(runner: repair.Runner, journal: dict, print_fn=print_tty1, *,
                                enforce_lan_only: bool = False) -> dict | None:
    try:
        config = config_pipeline.load_config(runner)
    except Exception as exc:  # noqa: BLE001 - never let a bad config file break firstboot
        print_fn(f"[baseline-firstboot] configurator settings: could not read config file - {exc}")
        return None
    if config is None:
        print_fn("[baseline-firstboot] configurator settings: no exported config file found - nothing to apply.")
        if enforce_lan_only:      # the LAN-only inbound policy does not depend on an exported config
            lan = config_pipeline.apply_stored_config(
                runner, None, network_interface=_DEFAULT_NETWORK_INTERFACE, enforce_lan_only=True)
            print_fn(f"[baseline-firstboot] LAN-only firewall: {'active' if lan['applied'] else 'NOT applied'}")
        return None
    summary = config_pipeline.apply_stored_config(
        runner, config, network_interface=_resolve_network_interface(journal), enforce_lan_only=enforce_lan_only)
    print_fn(f"[baseline-firstboot] configurator settings applied: {summary['applied']} "
              f"skipped: {summary['skipped']} failed: {summary['failed']}")
    for name, detail in summary.get("errors", {}).items():
        print_fn(f"[baseline-firstboot] {name}: {detail}")
    return summary


# ---------------------------------------------------------------------------
# The state machine itself.
# ---------------------------------------------------------------------------

def run(runner: repair.Runner, *, state_dir: Path = STATE_DIR, stdin=None,
        print_fn=print_tty1, check_lifeline_fn=None,
        offline_root: Path = OFFLINE_REPOSITORY, offline_sources: Path = OFFLINE_SOURCES) -> dict:
    completed_at = already_completed(state_dir)
    if completed_at is not None:
        print_fn(f"[baseline-firstboot] previous run already completed at {completed_at} - not re-triggering.")
        apply_configurator_settings(runner, load_journal(state_dir), print_fn, enforce_lan_only=True)
        return {"action": "already_completed", "completed_at": completed_at, "package_install_allowed": True}

    journal = load_journal(state_dir)
    if journal.get("journal_was_corrupted"):
        print_fn("[baseline-firstboot] journal was corrupted or unreadable - starting fresh from "
                 "discovery (fail-closed; no consequential state is ever resumed from an untrusted journal).")

    if journal["state"] == "new":
        journal = record_transition(state_dir, journal, "created")

    detection = None
    if journal["state"] == "created":
        detection = proxmox_detect.detect_proxmox_install(runner)
        journal = record_transition(state_dir, journal, "detected",
                                     proxmox_installed=detection.installed,
                                     proxmox_version=detection.version,
                                     proxmox_evidence=detection.evidence,
                                     proxmox_probe_errors=detection.errors)

    if journal["state"] == "detected":
        entry = _last(journal, "detected")
        if proxmox_detection_block(entry):
            # A previous unavailable observation is retried on each firstboot
            # invocation. It remains fail-closed until absence is established.
            if detection is None:
                detection = proxmox_detect.detect_proxmox_install(runner)
                journal = record_transition(state_dir, journal, "detected",
                                             proxmox_installed=detection.installed,
                                             proxmox_version=detection.version,
                                             proxmox_evidence=detection.evidence,
                                             proxmox_probe_errors=detection.errors)
                entry = _last(journal, "detected")
            block = proxmox_detection_block(entry)
            if block:
                detail = block["reason"]
                print_fn("[baseline-firstboot] Proxmox detection unavailable: " + detail)
                print_fn("[baseline-firstboot] remaining at tty1 - installer path refused until detection succeeds.")
                return block

    if journal["state"] == "detected":
        discovery = fbnr.discover(runner, check_lifeline_fn)
        journal = record_transition(state_dir, journal, "discovered", discovery=discovery)

    if journal["state"] == "discovered":
        discovery = _last(journal, "discovered")["discovery"]
        if discovery["lifeline_ok"]:
            diagnosis = {"needs_repair": False, "mode": None, "target": None, "diff": None, "reason": ""}
        else:
            diagnosis = fbnr.diagnose(runner, discovery)
        journal = record_transition(state_dir, journal, "proposed", diagnosis=diagnosis)

    if journal["state"] == "proposed":
        diagnosis = _last(journal, "proposed")["diagnosis"]
        if diagnosis["needs_repair"] and diagnosis["mode"] is None:
            print_fn(f"[baseline-firstboot] lifeline broken, no safe automatic repair could be derived: "
                      f"{diagnosis['reason']}")
            print_fn("[baseline-firstboot] remaining at tty1 - no automatic retry, no package installation.")
            return {"action": "refused", "reason": diagnosis["reason"], "package_install_allowed": False}

        detection_entry = _last(journal, "detected")

        class _Detection:  # lightweight re-hydration for the formatter
            installed = detection_entry["proxmox_installed"]
            evidence = detection_entry["proxmox_evidence"]

        discovery = _last(journal, "discovered")["discovery"]
        offline_now = offline_repository(offline_root, offline_sources)["available"]
        print_fn(format_full_proposal(_Detection(), discovery, diagnosis, offline_available=offline_now))
        confirmed = fbnr.wait_for_confirmation(stdin)
        if not confirmed:
            print_fn("[baseline-firstboot] not confirmed - no change made.")
            return {"action": "declined", "package_install_allowed": False}
        journal = record_transition(state_dir, journal, "confirmed")

    if journal["state"] == "confirmed":
        diagnosis = _last(journal, "proposed")["diagnosis"]
        discovery = _last(journal, "discovered")["discovery"]
        if diagnosis["needs_repair"]:
            if diagnosis["mode"] == "replace":
                repair_result = repair.reset_interface_to_dhcp(
                    runner, diagnosis["target"], "firstboot-statemachine",
                    operator_present=True, check_lifeline_fn=check_lifeline_fn)
            else:
                repair_result = repair_additive.add_dhcp_to_bridge(
                    runner, diagnosis["target"], "firstboot-statemachine",
                    operator_present=True, check_lifeline_fn=check_lifeline_fn)
            network_ok = bool(repair_result.ok)
            network_detail = repair_result.detail
            # Only genuinely-checked evidence, never fabricated - see
            # RepairResult.verification's docstring. Empty on failure,
            # by construction (repair.py/repair_additive.py only
            # populate it on their own success return).
            verification = dict(repair_result.verification)
            target_interface = diagnosis["target"]
        else:
            # Persisted discovery is a proposal, not current verification.
            current = fbnr.discover(runner, check_lifeline_fn)
            verification = fbnr.facts_verification(current["facts"])
            target_interface = fbnr.observed_dev(runner, current["facts"]) or ""
            network_ok = all(v is True for v in verification.values()) and bool(target_interface)
            network_detail = ("lifeline verified now - no repair needed" if network_ok else
                              "current address/gateway verification failed; retry discovery")

        print_fn(f"[baseline-firstboot] network result: {'success' if network_ok else 'FAILED'} - {network_detail}")
        if network_ok:
            journal = record_transition(state_dir, journal, "network_repaired", network_ok=True,
                                         target_interface=target_interface, verification=verification,
                                         network_detail=network_detail)
        else:
            journal = record_transition(state_dir, journal, "network_repair_failed",
                                         network_ok=False, network_detail=network_detail)

    if journal["state"] == "network_repair_failed":
        # Fresh or resumed, branch on the recorded state - never redo the
        # repair attempt or the diagnosis that led here. The failure stays
        # in the journal either way; nothing here ever writes
        # `network_repaired`, so its evidence invariant is untouched.
        failed_detail = _last(journal, "network_repair_failed")["network_detail"]
        repo = offline_repository(offline_root, offline_sources)
        if not repo["available"]:
            print_fn("[baseline-firstboot] networking did not verify and this drive carries no verified "
                     f"package repository ({repo['reason']}) - package installation refused, not committing.")
            return {"action": "network_failed", "detail": failed_detail, "package_install_allowed": False}
        print_fn("[baseline-firstboot] networking did not verify - recorded. Installing diagnostic tools from "
                 f"this drive's own repository instead ({repo['files_verified']} files re-verified); "
                 "no network source is used.")
        install_result = install_diagnostic_tools(runner, offline_sources=offline_sources)
        journal = record_transition(state_dir, journal, "packages_installed", package_source="offline",
                                     network_verified=False, offline_repository=repo, **install_result)
        if not install_result["ok"]:
            print_fn(f"[baseline-firstboot] offline package installation FAILED - not committing: "
                     f"{install_result['detail']}")
            return {"action": "packages_failed", "detail": install_result["detail"], "package_install_allowed": True}

    if journal["state"] == "network_repaired":
        # Reaching this state at all - fresh or resumed - already means
        # the repair succeeded (or the lifeline was already healthy);
        # see record_transition's invariant guard and the module
        # docstring. No network_ok re-check needed or possible here.
        print_fn("[baseline-firstboot] installing diagnostic tools...")
        install_result = install_diagnostic_tools(runner)
        journal = record_transition(state_dir, journal, "packages_installed", package_source="network",
                                     network_verified=True, **install_result)
        if not install_result["ok"]:
            print_fn(f"[baseline-firstboot] package installation FAILED - not committing: {install_result['detail']}")
            return {"action": "packages_failed", "detail": install_result["detail"], "package_install_allowed": True}

    if journal["state"] == "packages_installed":
        if not _last(journal, "packages_installed")["ok"]:
            return {"action": "packages_failed",
                    "detail": _last(journal, "packages_installed")["detail"],
                    "package_install_allowed": True}
        print_fn("[baseline-firstboot] verifying diagnostic tools...")
        verify_result = verify_diagnostic_tools(runner)
        journal = record_transition(state_dir, journal, "packages_verified", **verify_result)
        print_fn(f"[baseline-firstboot] verification: {'success' if verify_result['ok'] else 'FAILED'} - "
                  f"{verify_result.get('reason', '')}")
        if not verify_result["ok"]:
            print_fn("[baseline-firstboot] package verification FAILED - not committing.")
            return {"action": "packages_verify_failed", "detail": verify_result["reason"],
                     "package_install_allowed": True}

    if journal["state"] == "packages_verified":
        if not _last(journal, "packages_verified")["ok"]:
            return {"action": "packages_verify_failed",
                    "detail": _last(journal, "packages_verified").get("reason", ""),
                    "package_install_allowed": True}
        installed = _last(journal, "packages_installed")
        network_verified = any(e["state"] == "network_repaired" for e in journal["history"])
        mark_complete(state_dir)
        journal = record_transition(state_dir, journal, "committed", network_verified=network_verified,
                                     package_source=installed.get("package_source", "network"))
        if network_verified:
            print_fn("[baseline-firstboot] COMMITTED. Marker written - will not re-run automatically.")
        else:
            print_fn("[baseline-firstboot] COMMITTED OFFLINE. Marker written - will not re-run automatically. "
                     "Networking did NOT verify and was not repaired; that failure is recorded in the journal.")

    committed = _last(journal, "committed")
    apply_configurator_settings(runner, journal, print_fn, enforce_lan_only=True)
    print_fn("[baseline-firstboot] state machine run finished.")
    return {"action": "committed", "package_install_allowed": True,
            "network_verified": committed.get("network_verified", True),
            "package_source": committed.get("package_source", "network")}


def main() -> int:
    result = run(repair.RealRunner())
    return 0 if result.get("action") == "committed" or result.get("action") == "already_completed" else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
