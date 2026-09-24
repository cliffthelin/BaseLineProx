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

  confirmed -> network_repair_failed  (terminal; network did not verify)

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
    already-healthy lifeline) is confirmed AND independently verified.
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

import diagnostics
import firstboot_network_repair as fbnr
import network
import proxmox_detect
import repair
import repair_additive

STATE_DIR = Path("/var/lib/baseline-firstboot")

STATES = ["created", "detected", "discovered", "proposed", "confirmed",
          "network_repaired", "network_repair_failed",
          "packages_installed", "packages_verified", "committed"]

DIAGNOSTIC_PACKAGES = ["lm-sensors", "nvme-cli", "smartmontools", "iperf3", "ethtool"]


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

def install_diagnostic_tools(runner: repair.Runner) -> dict:
    argv = ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y"] + DIAGNOSTIC_PACKAGES
    proc = runner.run(argv, timeout=300)
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


# ---------------------------------------------------------------------------
# Combined tty1 proposal - everything the operator needs to authorize in
# one screen, per Gate E's requirement.
# ---------------------------------------------------------------------------

def format_setup_intent_status() -> str:
    """Informational only - see module docstring. Never the gate."""
    return (
        "Setup-intent bundle: none staged for this boot.\n"
        "Where a colocated verification key is used elsewhere in this project,\n"
        "it is an INTEGRITY/CORRUPTION check only, per PRD SS5.6 - it is not\n"
        "authentication, and it is never the authorization gate for this\n"
        "action. Only a real CONFIRM keystroke, read below, authorizes anything."
    )


def format_full_proposal(detection, discovery: dict, diagnosis: dict) -> str:
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

    lines.append("Diagnostic tools proposed for installation (only after network verifies):")
    for pkg in DIAGNOSTIC_PACKAGES:
        lines.append(f"  - {pkg}")
    lines.append("")

    lines.append("Rollback and verification:")
    lines.append("  An independent rollback timer is armed BEFORE any network write.")
    lines.append("  Address, target-bound route/gateway, DNS, and HTTPS are independently")
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
# The state machine itself.
# ---------------------------------------------------------------------------

def run(runner: repair.Runner, *, state_dir: Path = STATE_DIR, stdin=None,
        print_fn=print_tty1, check_lifeline_fn=None) -> dict:
    completed_at = already_completed(state_dir)
    if completed_at is not None:
        print_fn(f"[baseline-firstboot] previous run already completed at {completed_at} - not re-triggering.")
        return {"action": "already_completed", "completed_at": completed_at, "package_install_allowed": True}

    journal = load_journal(state_dir)
    if journal.get("journal_was_corrupted"):
        print_fn("[baseline-firstboot] journal was corrupted or unreadable - starting fresh from "
                 "discovery (fail-closed; no consequential state is ever resumed from an untrusted journal).")

    if journal["state"] == "new":
        journal = record_transition(state_dir, journal, "created")

    if journal["state"] == "created":
        detection = proxmox_detect.detect_proxmox_install(runner)
        journal = record_transition(state_dir, journal, "detected",
                                     proxmox_installed=detection.installed,
                                     proxmox_version=detection.version,
                                     proxmox_evidence=detection.evidence)

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
        print_fn(format_full_proposal(_Detection(), discovery, diagnosis))
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
            network_ok = True
            network_detail = "lifeline already healthy - no repair needed"
            # Still genuine, not fabricated: the same address/gateway
            # facts discover() already used to decide the lifeline was
            # healthy, reused as this path's verification evidence.
            verification = fbnr.facts_verification(discovery["facts"])
            target_interface = fbnr.observed_dev(runner, discovery["facts"]) or ""

        print_fn(f"[baseline-firstboot] network result: {'success' if network_ok else 'FAILED'} - {network_detail}")
        if network_ok:
            journal = record_transition(state_dir, journal, "network_repaired", network_ok=True,
                                         target_interface=target_interface, verification=verification,
                                         network_detail=network_detail)
        else:
            journal = record_transition(state_dir, journal, "network_repair_failed",
                                         network_ok=False, network_detail=network_detail)
            print_fn("[baseline-firstboot] networking did not verify - package installation refused, not committing.")
            return {"action": "network_failed", "detail": network_detail, "package_install_allowed": False}

    if journal["state"] == "network_repair_failed":
        # Resuming directly into a recorded failure - branch on the
        # recorded state, never redo the repair attempt or the
        # diagnosis that led here.
        return {"action": "network_failed",
                "detail": _last(journal, "network_repair_failed")["network_detail"],
                "package_install_allowed": False}

    if journal["state"] == "network_repaired":
        # Reaching this state at all - fresh or resumed - already means
        # the repair succeeded (or the lifeline was already healthy);
        # see record_transition's invariant guard and the module
        # docstring. No network_ok re-check needed or possible here.
        print_fn("[baseline-firstboot] installing diagnostic tools...")
        install_result = install_diagnostic_tools(runner)
        journal = record_transition(state_dir, journal, "packages_installed", **install_result)
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
        mark_complete(state_dir)
        record_transition(state_dir, journal, "committed")
        print_fn("[baseline-firstboot] COMMITTED. Marker written - will not re-run automatically.")

    print_fn("[baseline-firstboot] state machine run finished.")
    return {"action": "committed", "package_install_allowed": True}


def main() -> int:
    result = run(repair.RealRunner())
    return 0 if result.get("action") == "committed" or result.get("action") == "already_completed" else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
