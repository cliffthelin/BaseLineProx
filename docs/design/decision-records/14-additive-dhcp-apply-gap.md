# Decision record: the additive dual-stanza design does not actually apply DHCP — a real, unresolved architecture problem

Date: 2026-09-21
Investigator: Claude Code
Status: complete for this pass. **This is not a small bug — direct evidence shows the additive repair's core design premise (a second, separate `iface vmbr0 inet dhcp` stanza alongside the existing `inet6 static` one) does not work with this ifupdown2 version's real interface bring-up, even though it now passes `--syntax-check` cleanly after decision record 13's fix. Not fixed this pass — reported as a genuine open design problem, not papered over.**

## Scope discipline

No push to `cliffthelin/baseline`. No physical device. No package installed. No authorization-triggering call. One disposable QEMU install, discarded, retention policy applied (252KB retained, credentials confirmed absent via grep before deletion).

## What was tested

Following decision record 13's fix (the `ifreload --syntax-check` interactive/non-interactive exit-code mismatch), a fresh QEMU install reproduced genuine Fixture A again. With the fixed code, `ifreload -a` now reports success (exit 0) for the additive file — but `vmbr0` never acquires an IPv4 address (`ip -o -4 addr show vmbr0` returns nothing). This investigation exists to find out why.

## Direct evidence: `ifup -v vmbr0` never attempts DHCP for the second stanza

Ran `ifdown vmbr0; ifup -v vmbr0` (a full teardown/bring-up cycle, not just a reload) with verbose output captured. The full 64-line trace was inspected directly:

- `ifupdown2` logs exactly one `<iface>: running ops ...` pass for `vmbr0`.
- Every subsequent line is bridge/IPv6-specific: `netlink: ip link add dev vmbr0 type bridge`, `applying bridge settings`, `set bridge-fd 0`, `netlink: ip addr add fec0::.../64 dev vmbr0`, `ip route replace default via fe80::2 ...`.
- **`grep -i dhcp` against the entire trace returns zero matches.** No `dhclient` invocation, no DHCP-related log line of any kind, anywhere in the bring-up sequence.

This is direct, unambiguous evidence: ifupdown2's real bring-up path processes only **one** `iface vmbr0 ...` block for the interface name `vmbr0` — the `inet6 static` one — and never acknowledges the second `iface vmbr0 inet dhcp` block exists at all. This is a genuinely different code path from `--syntax-check`, which validates each stanza independently and has no objection to either one — the mismatch between "syntax-check treats both stanzas as individually valid" and "real bring-up only processes one of them" is itself worth naming plainly: passing syntax-check was never evidence that the additive design would actually work, and decision record 13 did not claim otherwise.

## Follow-up test: inconclusive, not a negative result — reported honestly

Attempted a follow-up test: reorder the stanzas (`inet dhcp` first, `inet6 static` second) to check whether ifupdown2 always processes whichever `iface vmbr0` block appears **first**, regardless of family — which would at least explain the mechanism precisely, even if it doesn't yield an immediate fix (two blocks aren't safely reorderable without deciding which family "loses"). This test could not be completed cleanly: the guest's console repeatedly went blank (ordinary console power-management blanking, not confirmed as a guest hang — `info status` via the QEMU monitor continued to report `running` throughout), and typed commands could not be reliably confirmed to execute before this investigation's time budget for chasing a flaky repro ran out. **No claim is made about stanza ordering's effect** — this remains genuinely untested, not tested-and-negative.

## What this means

The additive repair's premise — "the two families coexist as separate `iface` blocks, which is standard, valid ifupdown2 syntax for dual-stack configuration" (the original module docstring's own claim) — **is not supported by direct evidence against this ifupdown2 version's real bring-up behavior.** It may be valid syntax that classic `ifupdown` (the older, non-ifupdown2 tool) processes correctly, or it may require an ordering or additional directive this investigation didn't identify, or ifupdown2 may simply not support this pattern for bridges specifically. All three remain open possibilities; none is confirmed.

**This is now flagged as a design-level problem for the additive repair approach, not a small implementation bug to patch.** Recommended next steps for whoever picks this up, none attempted here:

1. Direct review of ifupdown2's own source (`addons/dhcp.py`, `addons/bridge.py`, and the core interface-dependency-graph/iface-merging logic) to understand exactly how — or whether — it's meant to handle two `iface <name>` stanzas sharing a name but different families, rather than inferring from behavior alone.
2. A real, controlled test of the reordering hypothesis this pass couldn't complete, with a fresh guest and console-blanking disabled or worked around (e.g. `setterm -blank 0`, or drive entirely through the QEMU monitor/serial console instead of VNC keystrokes for reliability).
3. Consider whether the additive case is better served by a completely different mechanism than a second `iface` stanza at all — e.g., invoking `dhclient vmbr0` (or ifupdown2's own dhcp addon script, if it can be invoked directly) as a supplementary action after the existing static family is confirmed up, rather than relying on ifupdown2's own file-driven family-merging to do it.

## What remains correctly fixed, unaffected by this finding

Decision record 13's fix (the `ifreload --syntax-check` advisory-warning handling) is real, tested, and independently valuable regardless of this finding — it fixes a genuine bug in how both repair paths (replace and additive) interpret that tool's exit code, and was directly verified to resolve the syntax-check refusal. This decision record does not walk that back; it reports a second, different, deeper problem found immediately afterward.

## Retained limitations, unchanged from decision records 12/13

The duplicate-stanza-name parser limitation, the permanent boot-time rollback service, and reboot-persistence verification remain exactly as previously stated.

## Whether Gates B–F may begin

No. Gate A does not pass, and this pass narrows the reason further: even with the syntax-check bug fixed, the additive repair does not actually establish working DHCP. The additive design itself needs revisiting before another Gate A attempt is worth running.
