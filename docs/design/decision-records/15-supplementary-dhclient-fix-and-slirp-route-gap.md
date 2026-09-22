# Decision record: supplementary `dhclient` fix confirmed working; a second, environment-specific gap found and scoped

Date: 2026-09-22
Investigator: Claude Code
Status: partial success. **The additive path's DHCP-apply gap (decision record 14) is now root-caused and fixed: a supplementary `dhclient <target>` call, confirmed directly in real QEMU, successfully acquires an address where ifupdown2's own bring-up does not. A second, distinct problem was then found — the acquired lease carries no default route — and is root-caused here as a QEMU/SLIRP test-environment limitation, not a defect in this project's code. No production-code workaround was added for it, for reasons explained below.**

## Scope discipline

No push to `cliffthelin/baseline`. No physical device. No package installed. No authorization-triggering call. One disposable QEMU workspace (`experiments/m1-gateA-v4`), retention policy to be applied after this record is written.

## Part 1: root-causing decision record 14's gap via ifupdown2 source review

Decision record 14 left three open possibilities for why `ifreload -a` silently skips the second `iface vmbr0 inet dhcp` stanza. This pass read the real, installed ifupdown2 source directly on the guest:

- `/usr/share/ifupdown2/ifupdown/networkinterfaces.py` — the stanza parser. Confirmed via direct reading that duplicate `iface <name>` blocks are each parsed into their own `iface` object correctly; nothing here merges or drops the second block. `ifquery vmbr0` was run and independently confirms both stanzas are recognized as separate ifaceobjs (their `addr_family` differs, `inet` vs `inet6`) — parsing is correct.
- The gap is at the **scheduler/dependency-graph level**, not parsing: ifupdown2 builds one dependency-graph node per interface **name**, and only the first ifaceobj registered for that name is what the scheduler actually runs operations against during real `ifup`/`ifreload` bring-up. This matches decision record 14's own observed trace evidence exactly (zero DHCP-related lines anywhere in a verbose `ifup -v vmbr0`) and is now understood as *why*, not just *that*.

This confirms decision record 14's recommendation #3 was the right direction: a second `iface` stanza is not a viable mechanism for ifupdown2 to apply a second family's config. A supplementary, explicit call is required.

## Part 2: supplementary `dhclient` — confirmed as a real, working fix

Direct manual testing (before touching any code) confirmed: running `dhclient <target>` against an already-up interface (bridge already exists via the working `inet6 static` stanza) successfully performs a real DHCPDISCOVER/OFFER/REQUEST/ACK exchange and binds an IPv4 address — independent of ifupdown2's own dispatch, which never touches the second stanza at all.

Also confirmed directly, as an important scoping check: the **replace path** (Fixture B's shape — a single, unambiguous `iface <name> inet dhcp` stanza) works correctly through ifupdown2's normal `ifup`/`ifreload -a` bring-up with **no** supplementary call needed. The gap is specific to the additive (dual-stanza) case, not a general problem with this project's use of ifupdown2.

### Implementation

Added a step "7b" to `add_dhcp_to_bridge()` in `baseline/lib/repair_additive.py`, between apply (step 7) and verify (step 8): a supplementary `runner.run(["dhclient", target.name], timeout=30)` call. Failure raises `RepairRefused("dhclient_failed", ...)` with rollback left armed (consistent with every other step in this pipeline). Logged via the existing `log_event` mechanism (`dhclient_supplementary`, pass/fail).

Unit tests added to `tests/unit/test_phase0_additive_repair.py` (FakeRunner-scripted, no real subprocess/device access):
- `test_supplementary_dhclient_is_invoked_after_apply`
- `test_dhclient_failure_refuses_and_leaves_rollback_armed`
- `test_replace_path_does_not_invoke_supplementary_dhclient` (guards against regressing the confirmed-working replace path by adding an unnecessary call to it)

Full suite: 81/81 passing before the real QEMU re-verification below.

### Real QEMU re-verification

Rebuilt the `experiments/m1-gateA-v4` disposable workspace, redeployed the fixed modules, ran the real Gate A pipeline (`run_gateAv4.py`) against genuine Fixture A. Result: the `dhclient_failed` refusal is gone — the supplementary call succeeds. `ip -o -4 addr show vmbr0` on the guest confirms a real DHCP-assigned address (`10.0.2.15/24`, `dynamic`). This is a genuine, verified fix for decision record 14's gap.

## Part 3: a second gap found immediately after — no default route

With the address-acquisition problem fixed, `add_dhcp_to_bridge()`'s own verification step (`verify_target_extended`, wrapping `repair.verify_target`) then failed at the route check: *"vmbr0 has an address but no default route via it."* The pipeline correctly rolled back (independent rollback stayed armed, as designed) rather than reporting false success.

### Root-causing this, not assuming it away

Checked directly on the guest, in order, rather than guessing:

1. `ip -4 route show dev vmbr0` and `ip -4 route show` (system-wide): only the kernel-derived local-subnet route (`10.0.2.0/24 dev vmbr0 proto kernel scope link src 10.0.2.15`) — no `default via` line anywhere.
2. `/var/lib/dhcp/dhclient.leases` and `dhclient.vmbr0.leases`: lease entries have `fixed-address`, `option subnet-mask`, `option dhcp-lease-time`, `option dhcp-message-type`, `option dhcp-server-identifier` — but **no `option routers` line**, on the very first check (a renewal-style `DHCPREQUEST`/`DHCPACK` against a cached lease).
3. To rule out a stale/cached-lease artifact, forced a **fully clean** negotiation: killed dhclient, deleted all lease files, flushed the interface's addresses and routes, re-ran `dhclient -v vmbr0` with full verbose output captured. The trace shows a complete, genuine `DHCPDISCOVER → DHCPOFFER → DHCPREQUEST → DHCPACK` cycle (not a renewal). The resulting lease **still has no `option routers` line**, and `ip -4 route show` after this clean bind still shows no default route.
4. To rule out local configuration suppressing the option even if offered, checked `/etc/dhcp/dhclient.conf` and the hook scripts directly: line 16 explicitly reads `request subnet-mask, broadcast-address, time-offset, routers, ...` — the default, unmodified Debian config, which **does** request the routers option. No `ignore routers` or similar suppression exists anywhere in the config or hooks.
5. Checked the actual QEMU invocation for this guest (`ps aux`): `-netdev user,id=net0,restrict=on`. This is QEMU's built-in SLIRP user-mode networking (not a real/external DHCP server), with `restrict=on` (blocks outbound access to the host, unrelated in principle to DHCP option content).

**Conclusion**: dhclient correctly requested the `routers` option; SLIRP's own minimal built-in DHCP server genuinely did not include one in either the renewal or the fully clean DISCOVER/OFFER/REQUEST/ACK exchange. This is a QEMU/SLIRP test-environment behavior, not a bug in dhclient, in `dhclient.conf`, or in this project's code.

### Why no production-code fix was written for this

A tempting "fix" would be to fall back to a guessed gateway (e.g., the DHCP server's own address, `dhcp-server-identifier`) when no `routers` option is present. This was deliberately **not** done: on real networks, the DHCP server and the default gateway are frequently different hosts (e.g. a dedicated DHCP appliance, a Windows DC, a container-based DHCP service, in a topology where the router is a separate box). Guessing "DHCP server == gateway" would be **wrong** on real hardware in exactly the cases this repair tool exists to handle safely, and would silently install an incorrect route rather than failing closed. The project's standing discipline (never generalize a QEMU/SLIRP-observed behavior into a production assumption; fail closed rather than guess) applies directly here.

The existing behavior — `verify_target` correctly detects the missing route and the pipeline correctly rolls back rather than reporting false success — is the right behavior for this finding, not a bug to patch around.

### Whether it's specific to `restrict=on`

Not conclusively separated from plain `-netdev user` in this pass — that would require relaunching the guest with `restrict=on` removed and repeating the clean-negotiation test, which was not done here (time-boxed; the underlying production-code conclusion above does not depend on the answer). Left as a genuinely open, explicitly-flagged question for whoever next touches the Gate A QEMU harness, not claimed either way.

## What this means for Gate A

Gate A still does not achieve a full, real, end-to-end pass (address + route + gateway + DNS + HTTPS all verified) in this QEMU/SLIRP test harness — but the reason has narrowed further and favorably: the code's own address-acquisition gap (decision record 14) is fixed and verified; the remaining blocker is a test-environment DHCP-server limitation that the pipeline correctly detects and fails closed on, not a defect in the repair logic. On real Proxmox hardware, where the site's real DHCP server almost always advertises a router option, this specific blocker would not be expected to occur — but that expectation itself has not been verified against real hardware in this project, and is stated here as an expectation, not a tested fact.

## What remains correctly fixed, unaffected by this finding

Decision record 13's syntax-check fix and this record's supplementary-dhclient fix are both real, unit-tested, and independently verified in real QEMU. Neither is walked back by this finding.

## Retained limitations, unchanged from prior decision records

- The duplicate-stanza-name parser limitation (decision records 12/14) remains a known, accepted, fail-closed gap.
- Reboot-persistence for the additive path's DHCP lease remains unbuilt — the supplementary `dhclient` call only covers the current invocation, not subsequent boots. Needs a boot-time systemd unit, matching the existing unbuilt `repair_rollback.py` boot-time-recovery precedent.
- The stanza-reordering hypothesis from decision record 14 remains genuinely untested.

## Whether Gates B–F may begin

No. Gate A has not achieved a full real-QEMU pass. The remaining blocker is now understood precisely (a SLIRP DHCP-option gap, not a code defect), and correctly fails closed rather than reporting false success — but "fails closed correctly" is not the same as "passes."
