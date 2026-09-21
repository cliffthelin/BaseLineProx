#!/usr/bin/env python3
"""Deterministic target-interface derivation for the host-network repair
action.

Replaces v1 of this design's mistake (assume the repair target is always a
physical NIC) with a real walk of the parsed ifupdown2 topology: a bridge's
own static config, not its physical member's `manual` stanza, is the actual
repair target on a standard Proxmox host. Never trusts a harness-proposed
target as the answer - `derive_target()` computes it independently from
`network.py`'s observed failing device plus the parsed config, and the
harness's proposal (if any) is only ever compared against that, logged as a
discrepancy when it disagrees, never substituted in.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ifnet_config import ParsedConfig, Stanza, classify


@dataclass
class TargetCandidate:
    name: str
    kind: str  # "physical" | "bridge" | "bond" | "vlan"
    stanza: Stanza
    physical_devices: list = field(default_factory=list)  # underlying physical device name(s)


@dataclass
class DerivationResult:
    target: TargetCandidate | None
    candidates: list  # 0, 1 (== target), or >1 (ambiguous)
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.target is not None


def _reverse_members(cfg: ParsedConfig) -> dict:
    """device name -> list of stanza names that reference it as a member
    (bridge-ports / bond-slaves / vlan-raw-device)."""
    rev: dict = {}
    for name, stanza in cfg.stanzas.items():
        kind = classify(stanza)
        if kind == "bridge":
            members = stanza.options.get("bridge-ports", "").split()
        elif kind == "bond":
            members = stanza.options.get("bond-slaves", "").split()
        elif kind == "vlan":
            parent = stanza.options.get("vlan-raw-device")
            members = [parent] if parent else []
        else:
            members = []
        for m in members:
            rev.setdefault(m, []).append(name)
    return rev


def _underlying_physical(name: str, cfg: ParsedConfig, rev: dict, seen: set) -> list:
    """Physical device names beneath `name` in the topology (empty if
    `name` is itself physical or unknown)."""
    stanza = cfg.stanzas.get(name)
    if stanza is None or name in seen:
        return []
    seen = seen | {name}
    kind = classify(stanza)
    if kind == "physical":
        return [name]
    out = []
    if kind == "bridge":
        for m in stanza.options.get("bridge-ports", "").split():
            out.extend(_underlying_physical(m, cfg, rev, seen) or [m])
    elif kind == "bond":
        for m in stanza.options.get("bond-slaves", "").split():
            out.extend(_underlying_physical(m, cfg, rev, seen) or [m])
    elif kind == "vlan":
        parent = stanza.options.get("vlan-raw-device")
        if parent:
            out.extend(_underlying_physical(parent, cfg, rev, seen) or [parent])
    return out


def _is_static_candidate(name: str, cfg: ParsedConfig) -> TargetCandidate | None:
    stanza = cfg.stanzas.get(name)
    if stanza is None or stanza.family != "inet" or stanza.method != "static":
        return None
    kind = classify(stanza)
    physical = _underlying_physical(name, cfg, {}, set()) if kind != "physical" else [name]
    return TargetCandidate(name=name, kind=kind, stanza=stanza, physical_devices=physical)


def _walk_upward(observed_dev: str, cfg: ParsedConfig, rev: dict) -> list:
    """BFS from `observed_dev` through reverse membership edges
    (physical -> its bridge/bond -> that bond's bridge, etc.), collecting
    every stanza found along the way that's `inet static` - not just the
    first one, since a genuinely ambiguous topology (rare, but possible)
    needs every candidate surfaced, not the first found."""
    found: dict = {}
    frontier = [observed_dev]
    seen = {observed_dev}
    while frontier:
        nxt = []
        for dev in frontier:
            for parent_name in rev.get(dev, []):
                if parent_name in seen:
                    continue
                seen.add(parent_name)
                cand = _is_static_candidate(parent_name, cfg)
                if cand is not None:
                    found[parent_name] = cand
                # keep walking upward even if this level wasn't static
                # itself (e.g. a bond that's a bridge member, static config
                # sitting on the bridge two levels up)
                nxt.append(parent_name)
        frontier = nxt
    return list(found.values())


def derive_target(observed_dev: str, cfg: ParsedConfig) -> DerivationResult:
    """`observed_dev`: the device name network.py's lifeline check
    attributed the failure to (from `_route_default()` / the failing
    `address_assigned`/`gateway_reachable` fact - on a normal Proxmox host
    with a `vmbr0` bridge, this is very often already `vmbr0` itself,
    since that's what carries the default route; the upward walk exists
    for the cases where it isn't, or where the topology is deeper)."""
    if observed_dev not in cfg.stanzas and observed_dev not in _reverse_members(cfg):
        return DerivationResult(None, [], f"{observed_dev!r} is not a device Baseline's parsed "
                                           "interfaces config knows about at all")

    rev = _reverse_members(cfg)
    candidates: dict = {}

    direct = _is_static_candidate(observed_dev, cfg)
    if direct is not None:
        candidates[direct.name] = direct

    for cand in _walk_upward(observed_dev, cfg, rev):
        candidates.setdefault(cand.name, cand)

    values = list(candidates.values())
    if not values:
        return DerivationResult(None, [], f"no inet static configuration found for {observed_dev!r} "
                                           "or anything it's a member of - nothing for this action to reset")
    if len(values) > 1:
        names = ", ".join(sorted(c.name for c in values))
        return DerivationResult(None, values, f"multiple credible management-interface candidates found "
                                               f"({names}) - refusing rather than guessing which one to change")
    return DerivationResult(values[0], values, "")


# --------------------------------------------------------------------------
# Additive derivation: the observed device (or something it's a member of)
# has no `inet` (IPv4) stanza at all - only a non-inet (in practice, an
# `inet6 static`) one, or none. `derive_target` above only ever recognizes
# `inet static` stanzas as replace-candidates and correctly refuses
# ("no_static_config") on this shape; it was never meant to touch IPv6.
# This is the additive counterpart: find the single stanza eligible for a
# NEW, separate `inet dhcp` stanza to be added alongside whatever's
# already there, never replacing or deleting the existing stanza. See
# ifnet_config.add_dhcp_stanza for the corresponding rewrite.
# --------------------------------------------------------------------------

def _is_additive_candidate(name: str, cfg: ParsedConfig) -> TargetCandidate | None:
    """A stanza with a non-inet (e.g. inet6) static configuration and NO
    inet stanza of its own - eligible for an additive `inet dhcp` stanza.
    If an `inet` stanza already exists for `name`, this is a replace case
    (derive_target's job), not additive - never both."""
    stanza = cfg.stanzas.get(name)
    if stanza is None or stanza.family == "inet" or stanza.method != "static":
        return None
    kind = classify(stanza)
    physical = _underlying_physical(name, cfg, {}, set()) if kind != "physical" else [name]
    return TargetCandidate(name=name, kind=kind, stanza=stanza, physical_devices=physical)


def _walk_upward_additive(observed_dev: str, cfg: ParsedConfig, rev: dict) -> list:
    """Same BFS shape as _walk_upward, but collecting additive candidates
    instead of inet-static replace candidates."""
    found: dict = {}
    frontier = [observed_dev]
    seen = {observed_dev}
    while frontier:
        nxt = []
        for dev in frontier:
            for parent_name in rev.get(dev, []):
                if parent_name in seen:
                    continue
                seen.add(parent_name)
                cand = _is_additive_candidate(parent_name, cfg)
                if cand is not None:
                    found[parent_name] = cand
                nxt.append(parent_name)
        frontier = nxt
    return list(found.values())


def derive_additive_target(observed_dev: str, cfg: ParsedConfig) -> DerivationResult:
    """The additive counterpart to derive_target - only ever called after
    derive_target itself has already failed with "no inet static
    configuration found" (a caller mixing this up with derive_target's
    success path is a caller bug, not handled defensively here, matching
    this module's existing style of trusting its own pipeline rather than
    re-validating every internal invariant everywhere)."""
    if observed_dev not in cfg.stanzas and observed_dev not in _reverse_members(cfg):
        return DerivationResult(None, [], f"{observed_dev!r} is not a device Baseline's parsed "
                                           "interfaces config knows about at all")

    rev = _reverse_members(cfg)
    candidates: dict = {}

    direct = _is_additive_candidate(observed_dev, cfg)
    if direct is not None:
        candidates[direct.name] = direct

    for cand in _walk_upward_additive(observed_dev, cfg, rev):
        candidates.setdefault(cand.name, cand)

    values = list(candidates.values())
    if not values:
        return DerivationResult(None, [], f"no static configuration of any family found for {observed_dev!r} "
                                           "or anything it's a member of - nothing for an additive DHCP "
                                           "stanza to attach to")
    if len(values) > 1:
        names = ", ".join(sorted(c.name for c in values))
        return DerivationResult(None, values, f"multiple credible management-interface candidates found "
                                               f"({names}) - refusing rather than guessing which one to change")
    return DerivationResult(values[0], values, "")
