#!/usr/bin/env python3
"""Additive host-network repair - the IPv6-only-bridge counterpart to
`repair.reset_interface_to_dhcp`.

Why this is a separate module rather than a change to repair.py: Milestone
0/1's Phase 0 investigation reproduced the actual default Proxmox automated-
install networking result as a bridge (`vmbr0`) carrying only an `inet6
static` stanza (a deprecated-prefix SLAAC address, in practice) with no
`inet` (IPv4) stanza at all - see
docs/design/decision-records/10-m1-phase0-network-resolution.md. The
existing `reset_interface_to_dhcp` action is deliberately scoped to `inet`
stanzas only ("Scope: `inet` stanzas only", ifnet_config.py's own
docstring) and correctly refuses this shape with `no_static_config` -
this is not a bug in that action, since it was designed to *replace* a
broken static stanza, not to *add* a missing address family. See
docs/design/decision-records/11-repair-branch-comparison.md for the full
comparison this module is built from.

This module adds a distinct, ADDITIVE repair: given a bridge (or other
interface) with a static, non-inet configuration and no inet stanza,
propose and apply a NEW, separate `iface <name> inet dhcp` stanza,
leaving the existing (e.g. inet6) stanza completely untouched - never
silently deleted or rewritten. Establishing working IPv4 first, and
treating removal of stale IPv6 configuration as a separate, later,
explicitly authorized action, is a deliberate product decision (per
review), not an oversight: this module never deletes anything.

Every precondition, the backup, the independent rollback, the write, the
reload, and the verification reuse repair.py's already-reviewed,
already-tested machinery directly (imported, not reimplemented) - only
the derivation (topology.derive_additive_target) and the rewrite
(ifnet_config.add_dhcp_stanza) differ from the replace path.
"""
from __future__ import annotations

import uuid

import ifnet_config
import network
import repair
import topology
from repair import (
    RepairRefused,
    RepairResult,
    Runner,
    DEFAULT_ROLLBACK_WINDOW_S,
)


PROBE_HOST = "deb.debian.org"  # a real, already-relied-upon (apt) destination - not a synthetic canary host


def verify_target_extended(runner: Runner, target_interface: str, probe_host: str = PROBE_HOST,
                            stabilize: bool = True) -> repair.VerificationResult:
    """Extends repair.verify_target (address/route/gateway-ping) with the
    two checks that mattered most in Milestone 0's Phase 0 finding: a
    configuration can have a syntactically-present address and route and
    still be completely unreachable (decision record 10's Fixture B had
    exactly this shape - a route to a gateway that led nowhere). DNS
    resolution and outbound HTTPS are checked target-bound (`curl
    --interface <dev>`), matching Phase 0's own direct ping/curl
    methodology rather than trusting configuration shape alone.
    """
    base = repair.verify_target(runner, target_interface, stabilize=stabilize)
    if not base.ok:
        return base

    dns_res = runner.run(["getent", "hosts", probe_host], timeout=5)
    if dns_res.returncode != 0 or not dns_res.stdout.strip():
        return repair.VerificationResult(False, address=base.address, gateway=base.gateway,
                                          detail=f"DNS resolution for {probe_host} failed")

    https_res = runner.run(["curl", "-sS", "--interface", target_interface, "-o", "/dev/null",
                             "-m", "8", "-w", "%{http_code}", f"https://{probe_host}/"], timeout=12)
    code = https_res.stdout.strip()
    if https_res.returncode != 0 or not code.isdigit() or code == "000":
        return repair.VerificationResult(False, address=base.address, gateway=base.gateway,
                                          detail=f"outbound HTTPS to {probe_host} via {target_interface} failed "
                                                 f"(curl exit={https_res.returncode}, http_code={code!r})")

    return repair.VerificationResult(True, address=base.address, gateway=base.gateway,
                                      detail="address, route, gateway, DNS, and outbound HTTPS all verified "
                                             "through the target interface itself")


def plan_additive_repair(runner: Runner, observed_dev: str, proposed_target: str = "") -> topology.DerivationResult:
    """Read-only: derive the additive target. Callers should have already
    tried `repair.plan_repair()` (the replace-path derivation) and only
    fall back to this when that specifically failed with no candidate at
    all (not ambiguity, not anything else) - `plan_and_derive` below does
    exactly this ordering and is the entry point most callers want."""
    cfg = repair.read_interfaces_config(runner)
    return topology.derive_additive_target(observed_dev, cfg)


def plan_and_derive(runner: Runner, observed_dev: str, proposed_target: str = ""):
    """Try the existing replace-path derivation first (unchanged
    behavior, unchanged priority); only fall back to the additive
    derivation if replace found no inet-static candidate at all. Returns
    (mode, DerivationResult) where mode is "replace" or "additive" - the
    caller uses this to decide which rewrite function to apply. If BOTH
    fail, returns ("replace", <the replace failure>) so existing refusal
    codes/messages are preserved unchanged for the common case."""
    replace_result = repair.plan_repair(runner, observed_dev, proposed_target)
    if replace_result.ok:
        return "replace", replace_result
    if replace_result.candidates:
        # Ambiguous under the replace derivation - do not also try
        # additive; an ambiguous topology is ambiguous regardless of
        # which family the fix would touch.
        return "replace", replace_result
    additive_result = plan_additive_repair(runner, observed_dev, proposed_target)
    if additive_result.ok or additive_result.candidates:
        return "additive", additive_result
    # Neither path found anything - surface the original replace-path
    # refusal reason, since it's the more specific/informative one for
    # the "nothing here at all" case.
    return "replace", replace_result


def add_dhcp_to_bridge(runner: Runner, observed_dev: str, requested_by: str,
                        proposed_target: str = "", operator_present: bool = False,
                        rollback_window_s: int = DEFAULT_ROLLBACK_WINDOW_S,
                        check_lifeline_fn=None) -> RepairResult:
    """The additive repair pipeline. Mirrors
    repair.reset_interface_to_dhcp's transactional shape exactly (same
    nine steps, same refusal codes reused where the concept is the
    same), substituting derive_additive_target for derive_target and
    add_dhcp_stanza for rewrite_stanza_to_dhcp at steps 1-2 and 5. Every
    other step (backup, independent rollback, concurrent-edit check,
    syntax validation, apply, target-bound verification, event logging)
    calls repair.py's own functions directly - not reimplemented here.
    """
    check_lifeline_fn = check_lifeline_fn or network.check_lifeline
    attempt_id = str(uuid.uuid4())
    repair.log_event(runner, attempt_id, "proposed", "info",
                      f"observed_dev={observed_dev} proposed_target={proposed_target!r} "
                      f"requested_by={requested_by} mode=additive")

    try:
        # --- 1: discover topology / 2: validate candidate ---
        repair.check_standalone_host(runner)

        cap = repair.detect_ifupdown2(runner)
        if not cap.present:
            raise RepairRefused("unsupported_environment", cap.detail)

        derivation = plan_additive_repair(runner, observed_dev, proposed_target)
        if not derivation.ok:
            raise RepairRefused("topology_ambiguous" if len(derivation.candidates) > 1 else "no_additive_candidate",
                                 derivation.reason, candidates=derivation.candidates)
        target = derivation.target
        if proposed_target and proposed_target != target.name:
            repair.log_event(runner, attempt_id, "target_discrepancy", "info",
                              f"harness proposed {proposed_target!r}, Baseline derived {target.name!r} "
                              "- using the derivation")

        facts = check_lifeline_fn()
        fact_map = {f["fact"]: f for f in facts}
        gw_fact = fact_map.get("gateway_reachable")
        addr_fact = fact_map.get("address_assigned")
        if (gw_fact is None or gw_fact["ok"]) and (addr_fact is None or addr_fact["ok"]):
            raise RepairRefused("already_healthy",
                                 f"{target.name} currently reports address_assigned/gateway_reachable OK - "
                                 "refusing to change a device that isn't actually broken")

        sessions = repair.check_connection_guard(runner, target.physical_devices, operator_present)
        if sessions:
            repair.log_event(runner, attempt_id, "protected_sessions_disclosed", "info",
                              f"{len(sessions)} protected session(s), operator present, proceeding with disclosure",
                              protected_ports=sorted({s.local_port for s in sessions}))

        repair.log_event(runner, attempt_id, "validated", "info",
                          f"target_interface={target.name} mode=additive",
                          target_interface=target.name, topology=target.kind)

        # --- record the pre-existing non-inet stanza as detected residual
        # configuration - this repair never touches it, but its presence
        # is worth a durable record for the later, separately-authorized
        # cleanup action this design deliberately defers (see module
        # docstring). Not a claim that it has been repaired or removed.
        repair.log_event(runner, attempt_id, "residual_config_detected", "info",
                          f"{target.name} retains its existing {target.stanza.family} "
                          f"{target.stanza.method} stanza unchanged; this repair only adds "
                          "a new inet dhcp stanza alongside it",
                          residual_family=target.stanza.family, residual_method=target.stanza.method)

        # --- 3: create and byte-verify backup ---
        cfg = repair.read_interfaces_config(runner)
        backup = repair.create_backup(runner, attempt_id, cfg)
        repair.log_event(runner, attempt_id, "backup_written", "info", "backup byte-verified",
                          backup_hash=backup["closure_hash"])

        # --- 4: arm independent rollback, before any write ---
        unit = repair.arm_rollback(runner, attempt_id, rollback_window_s)
        repair.write_pending_manifest(runner, attempt_id, target.name, unit)
        repair.log_event(runner, attempt_id, "rollback_armed", "info", f"unit={unit} window={rollback_window_s}s",
                          rollback_unit=unit)

        # --- revalidate immediately before writing: closure must be unchanged ---
        cfg_now = repair.read_interfaces_config(runner)
        if ifnet_config.hash_closure(cfg_now.files) != backup["closure_hash"]:
            repair.cancel_rollback(runner, unit)
            repair.clear_pending_manifest(runner)
            repair.close_attempt(runner, attempt_id, "refused_concurrent_change")
            raise RepairRefused("concurrent_config_change",
                                 "interfaces config changed since the backup was taken - refusing to overwrite "
                                 "a change this action didn't make or review; a fresh proposal is needed")

        # --- 5: write candidate atomically (ADDITIVE: append, never replace) ---
        try:
            new_files = ifnet_config.add_dhcp_stanza(cfg_now, target.name)
        except ifnet_config.RewriteError as exc:
            restored, restore_detail = repair.restore_backup(runner, attempt_id)
            repair.cancel_rollback(runner, unit)
            repair.clear_pending_manifest(runner)
            repair.close_attempt(runner, attempt_id, "refused_rewrite_error")
            raise RepairRefused("rewrite_error", f"{exc}; restore: {restore_detail}")

        for path, text in new_files.items():
            if text != cfg_now.files[path]:
                runner.write_text_atomic(path, text)
        repair.log_event(runner, attempt_id, "written", "info",
                          f"{target.name} gained an additive inet dhcp stanza "
                          f"(existing {target.stanza.family} {target.stanza.method} stanza preserved unchanged)")

        # --- 6: validate syntax without applying ---
        check = runner.run(["ifreload", "--syntax-check", "-a"], timeout=15)
        if check.returncode != 0:
            restored, restore_detail = repair.restore_backup(runner, attempt_id)
            repair.cancel_rollback(runner, unit)
            repair.clear_pending_manifest(runner)
            repair.close_attempt(runner, attempt_id, "refused_syntax_invalid")
            repair.log_event(runner, attempt_id, "restored", "info" if restored else "fail", restore_detail)
            raise RepairRefused("syntax_invalid",
                                 f"ifreload --syntax-check failed: {check.stderr.strip()}; restore: {restore_detail}")

        # --- 7: apply ---
        apply_res = runner.run(["ifreload", "-a"], timeout=30)
        repair.log_event(runner, attempt_id, "applied", "pass" if apply_res.returncode == 0 else "fail",
                          apply_res.stderr.strip() if apply_res.returncode else "ifreload -a completed")
        if apply_res.returncode != 0:
            # Leave the independent rollback armed per spec - do not race
            # it with an inline restore.
            raise RepairRefused("apply_failed", f"ifreload -a failed: {apply_res.stderr.strip()}; "
                                                 "independent rollback stays armed")

        # --- 8: verify lifeline, target-bound (address/route/gateway/DNS/HTTPS) ---
        verification = verify_target_extended(runner, target.name)
        if not verification.ok:
            repair.log_event(runner, attempt_id, "verify_timeout", "fail", verification.detail)
            return RepairResult(False, attempt_id, "rolled_back",
                                 f"target-bound verification failed ({verification.detail}); "
                                 "independent rollback remains armed and will restore the original config")

        repair.log_event(runner, attempt_id, "verify_pass", "pass",
                          f"address={verification.address} gateway={verification.gateway}")

        # --- 9: cancel rollback only on success ---
        repair.cancel_rollback(runner, unit)
        repair.clear_pending_manifest(runner)
        repair.close_attempt(runner, attempt_id, "success")
        repair.log_event(runner, attempt_id, "cancelled_rollback", "info", "verification succeeded")
        return RepairResult(True, attempt_id, "success",
                             f"{target.name} gained a new inet dhcp stanza (existing "
                             f"{target.stanza.family} stanza preserved); "
                             f"address={verification.address} gateway={verification.gateway}")

    except RepairRefused as refusal:
        repair.log_event(runner, attempt_id, "refused", "fail", refusal.detail, code=refusal.code)
        return RepairResult(False, attempt_id, "refused", f"{refusal.code}: {refusal.detail}")
