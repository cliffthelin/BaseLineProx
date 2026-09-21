# Decision record: `ifreload --syntax-check` interactive/non-interactive exit-code fix, and a newly-found dual-stanza apply gap

Date: 2026-09-21
Investigator: Claude Code
Status: complete. **One real, confirmed bug found and fixed, with 78/78 unit tests passing and real QEMU verification that the fix works as intended. One additional, deeper, genuinely unresolved problem found in the process — not fixed this pass, reported honestly rather than papered over.**

## Scope discipline

No push to `cliffthelin/baseline`. No physical device touched. No package installed. No sudo/pkexec/polkit/authorization-triggering call at any point. Two disposable QEMU installs (both discarded, retention policy applied, confirmed no credential leakage via grep before deletion).

## What was investigated

Following up directly on decision record 12's Gate A finding: `ifreload --syntax-check` refused the additive repair, reporting a `bridge-fd` range warning as fatal. Record 12 hypothesized this was about stanza placement relative to the trailing `source` directive.

## First attempt: placement fix (partially right, not the root cause)

Fixed `ifnet_config.add_dhcp_stanza()` to insert the new stanza immediately after the target's own block instead of at the absolute end of the file (previously landing after the `source /etc/network/interfaces.d/*` line — non-standard Debian layout). This is a real, independently-justified improvement (conventional placement, confirmed via a new test locking in the exact expected output) and was kept. **It did not fix the actual failure** — a fresh QEMU run with the corrected placement hit the identical `syntax_invalid` refusal.

## Real root cause, isolated methodically against live infrastructure

Direct, controlled tests against the real, running guest (not assumptions):

1. `ifreload --syntax-check -a`, typed interactively in the guest's own shell, against the **unmodified, original, single-stanza Fixture A file**: exit 0, with the `bridge-fd` warning printed.
2. The exact same command, invoked via Python's `subprocess.run()` (matching `RealRunner.run()` exactly — no shell, no TTY) against the **same unmodified file**: **exit 1**, identical warning text.

This isolates the actual cause completely: **`ifreload --syntax-check`'s exit code depends on whether it's attached to an interactive terminal, not on anything about the file content, the additive stanza, or its placement.** It reproduces against a stock, unmodified, Proxmox-installer-generated config with no repair action involved at all. Every non-interactive caller of `ifreload --syntax-check` — this repair action and, equally, the *existing*, previously-imported `reset_interface_to_dhcp` replace path — was carrying this same landmine; it was never specific to the additive extension.

## Fix

Added `repair._syntax_check_advisory_only(stderr)`: returns true only when every non-blank line of the check's stderr is a `warning:`-prefixed message — exactly the class of output directly confirmed non-fatal when `ifreload` runs interactively. Wired into both syntax-check call sites (`repair.reset_interface_to_dhcp`'s step 6 and `repair_additive.add_dhcp_to_bridge`'s step 6): a non-zero exit now only refuses when it is *not* advisory-only; an advisory-only non-zero exit is logged (`syntax_check_advisory`) and the pipeline proceeds. Anything else — no output, a mix of warning and non-warning lines, a genuine `error:`-class message — still refuses exactly as before; this stays fail-closed for anything not directly evidenced as safe.

Five new unit tests cover the helper directly (multiple warnings, mixed content, empty stderr, genuine error), plus two pipeline-level tests confirming an advisory-only warning lets **both** the additive and the replace path proceed to success rather than refusing. 78/78 tests passing.

## Real QEMU verification of the fix

A second fresh disposable install (unmodified Fixture A, no `ipv6=off`), fixed code injected and staged at the production path. Running the full first-boot flow again:

- Discovery, diagnosis, and the exact-diff proposal all worked as before.
- **The syntax-check refusal is gone** — confirmed directly: the pipeline now proceeds past step 6, applies (`ifreload -a`, exit 0), and reaches target-bound verification. This is the fix working, verified against real infrastructure, not just the unit-test mock.
- Verification then failed for a **new, different reason** (below) — not the bug this pass targeted, and not silently declared fixed.

## A second, deeper, genuinely unresolved problem — found, not fixed

After the syntax-check fix, `ifreload -a` reports success (exit 0), but **`vmbr0` never actually acquires an IPv4 address** — confirmed directly: `ip -o -4 addr show vmbr0` returns nothing after the apply. Tested two different real application paths, both with the same result:

- `ifreload -a` (the pipeline's own call): interface stays up, IPv6 addressing intact, no IPv4 address, target-bound verification correctly fails (`vmbr0 has no IPv4 address`) and the independent rollback correctly remains armed to restore the original config — the pipeline's fail-closed behavior held correctly here too.
- A full manual `ifdown vmbr0 && ifup vmbr0` cycle (ruling out "reload vs. fresh bring-up" as the explanation): identical result — no IPv4 address acquired.

**This means the additive approach's core premise — that a second, separate `iface vmbr0 inet dhcp` stanza alongside the existing `inet6 static` one is sufficient for ifupdown2 to actually bring up DHCP on that family — is not confirmed and, on this evidence, appears wrong**, at least for this ifupdown2 version's real `ifup`/`ifreload` bring-up path (as opposed to its syntax checker, which validates each stanza independently and has no objection). The syntax-check bug and this apply-time gap are two distinct, unrelated failures that happened to be encountered back-to-back — fixing the first was necessary to even observe the second.

## What this means for Gate A

Genuine progress: one real, confirmed, load-bearing bug (affecting the whole application's use of `ifreload --syntax-check`, not just this feature) is fixed, tested, and verified against real infrastructure. Gate A still does not pass — a different, deeper problem now blocks it, and this record does not claim otherwise. The additive (dual-stanza) design itself may need reconsidering — options for a follow-up investigation include: explicit ifupdown2 documentation/source review for how it's actually meant to express "add DHCP to an interface that already has a static stanza for a different family" during real bring-up (not just syntax validation), testing whether `ifup vmbr0=vmbr0 inet dhcp`-style family-scoped invocation behaves differently, or reconsidering whether the additive approach is the right shape at all versus some other mechanism ifupdown2 actually supports for this case. None of that work was done in this pass — it's the next thing to investigate, not solved here.

## Retained limitations, unchanged from decision record 12

The duplicate-stanza-name parser limitation, the permanent boot-time rollback service, and reboot-persistence verification remain exactly as stated in decision record 12 — this pass didn't touch or re-evaluate them.

## Artifacts retained or deleted

Both disposable images/ISOs deleted after evidence capture, credentials confirmed absent from retained logs via grep before deletion. 360KB retained (`experiments/m1-gateA-v2/`, gitignored, not committed): screenshots and logs only.

## Whether Gates B–F may begin

No — unchanged. Gate A still does not pass. This pass narrows the blocker from "the pipeline refuses before even trying to apply" to "the apply appears to succeed but doesn't actually establish working DHCP for the added family" — a real step forward in diagnosis, not a resolution.
