# Decision record: Gate A's additive repair achieves a full apply-time pass — first in this project's history — but reboot-persistence still fails, now directly confirmed rather than theoretical

Date: 2026-09-22
Investigator: Claude Code
Status: **genuine, independently-verified progress.** The additive repair pipeline (`repair_additive.add_dhcp_to_bridge`), run against a directly-staged, byte-exact reproduction of Fixture A, achieves a full apply-time pass — address, route, gateway, DNS, and HTTPS all independently confirmed working — for the first time in this project's history. The previously-open reboot-persistence gap (theorized in decision records 14/15/16, never directly tested) is now directly confirmed: the fix does not survive a reboot. **Gate A still does not fully pass** — reboot-persistence is one of its explicit criteria.

## Scope discipline

No push to `cliffthelin/baseline`. No physical device. No host package installation. No privilege escalation. One disposable QEMU workspace (`experiments/m1-gateA-v4/runs/gateAv7-Nx8Ktm`), cleaned per retention policy (no credential-leak check needed — this workspace used a synthetic, disposable throwaway password by design, not a real credential; confirmed absent from all retained logs regardless).

## Why this methodology, not the usual one

Decision record 16 (and its confirmatory update) established that this host's `guestfwd` mechanism — the automated/answer-file install path every prior Gate A attempt has depended on — is currently, persistently broken: five independent reproduction attempts, spanning hours and heavy intervening successful SLIRP activity, all hung identically. Root cause remains unresolved (blocked on `CAP_NET_RAW` for packet capture, or a host reboot not yet taken).

Rather than continue blocked on that unresolved infrastructure problem, this pass used a different, already-proven-reliable path: the **interactive Terminal UI installer**, driven via VNC keystroke automation exactly as used successfully for last night's real `/dev/sdc` migration — which needs no guestfwd, no ephemeral answer server, no TLS at all. After a normal disposable install completed, Fixture A's exact byte content (`FIXTURE_A_IPV6_ONLY` from `tests/unit/test_phase0_additive_repair.py`) was written directly to `/etc/network/interfaces` and applied via `ifreload -a` (confirmed `IFRELOAD_EXIT=0`), reproducing the exact starting state the additive repair pipeline is meant to fix — without re-deriving the claim that this shape occurs from a real installer run, which decision record 10 already established with real evidence and this pass does not need to re-prove.

One adaptation was necessary and is itself informative: this fresh install's physical interface was named `nic0` (with altnames `enp0s3`/`enx525400ba5e12`), not `ens3` as in the original fixture and every prior gateA-v4/v5 workspace. The fixture was rewritten to use the interface name this environment actually produced, not blindly copied. Interface naming is evidently not stable across installs on this host even with an identical QEMU/SLIRP configuration — a fact worth keeping in mind for any future code that assumes a fixed interface name (the additive repair pipeline itself does not; it derives the observed device name dynamically, and this pass is a real, if incidental, stress test of that).

## What passed, with direct evidence

After staging Fixture A (confirmed via `ip -4 addr show vmbr0` returning nothing and `ip -6 addr show vmbr0` showing exactly the fixture's `fec0::.../64` and `fe80::.../64` addresses), the additive repair driver (`run_gateAv7.py`, calling `repair_additive.add_dhcp_to_bridge` with `observed_dev="nic0"`) was run for real, against genuine `ifupdown2`, genuine `dhclient`, genuine SLIRP DHCP.

Result: `outcome: "success"`, `detail: "vmbr0 gained a new inet dhcp stanza (existing inet6 stanza preserved); address=10.0.2.15 gateway=10.0.2.2"`.

Independently re-verified afterward, not just trusted from the pipeline's own report:
- `ip -4 addr show vmbr0` → `inet 10.0.2.15/24 ... dynamic vmbr0` (real DHCP-assigned address, confirmed dynamic not static).
- `ip -4 route show` → `default via 10.0.2.2 dev vmbr0` (a real default route — **present** this time, unlike decision record 15's finding).
- `getent hosts deb.debian.org` → resolved successfully.
- `wget https://deb.debian.org/` → `HTTPS_OK`.
- `cat /etc/network/interfaces` → both stanzas present: the original `iface vmbr0 inet6 static` block unmodified, plus a new `iface vmbr0 inet dhcp` block appended — the additive design working exactly as intended, non-destructively.

This is the first time in this project's history — across decision records 10 through 16 — that the additive repair's target-bound verification (address + route + gateway + DNS + HTTPS) has fully passed against a real QEMU environment.

## Why this differs from decision record 15's missing-router-option finding

Decision record 15 found, with equally direct evidence, that SLIRP's DHCP server did not send a `routers` option in that session, on that host state, causing the supplementary `dhclient` call to acquire an address with no route. This pass's SLIRP DHCP server, in a fresh QEMU process, on the same host, **did** send a `routers` option (`option routers 10.0.2.2` implied by the resulting default route). No code change explains the difference — `repair_additive.py` is unchanged since decision record 15/16.

This means the missing-router-option behavior is **not a fixed, permanent property of this host's SLIRP** — it appears to vary session to session, for reasons not identified (not re-investigated here; doing so would require the same root-level packet capture this project has repeatedly been unable to use). The correct, honest conclusion: SLIRP's DHCP router-option behavior on this host is **inconsistent across sessions**, confirmed by direct contradictory evidence from two independent real test runs, not resolved to a single explanation. The additive repair's own behavior (correctly using whatever route information DHCP actually provides, never guessing) is unaffected by this and remains the right design regardless of which way SLIRP behaves in a given session.

## What did not pass: reboot-persistence, now directly confirmed

Rebooted the guest (`reboot`, clean shutdown/restart, not a forced kill) and re-checked immediately after login: `ip -4 addr show vmbr0` and `ip -4 route show` both returned **nothing** — no IPv4 address, no default route, on the very next boot.

This confirms directly, for the first time (prior decision records only theorized it from the mechanism's shape, without a real reboot test against a real apply-time success), the gap already named in decision records 14/15/16: the supplementary `dhclient <target>` call in `repair_additive.add_dhcp_to_bridge` runs once, at apply time, as part of the repair pipeline's own transactional steps — it is not re-triggered on subsequent boots. `ifupdown2`'s own boot-time dispatch still only processes the first `iface vmbr0` stanza it finds (the `inet6 static` one, unaffected and correctly still comes up), never the second (`inet dhcp`) one, exactly as decision record 14 found for the original apply path.

The `inet dhcp` stanza itself **does** persist in `/etc/network/interfaces` (it's a file on disk, untouched by reboot) — only the actual DHCP negotiation that makes it functional does not re-run automatically.

## What this means for Gate A

Gate A's stated criteria include "config remains functional across reboot." That criterion **fails**, confirmed directly. The apply-time criteria (address + route + gateway + DNS + HTTPS immediately after repair) **pass**, confirmed directly, for the first time. Gate A as a whole still does not pass.

## Recommended next step, not attempted here

A boot-time systemd unit (matching the precedent already named as unbuilt in `repair_rollback.py`'s own module docstring for the reboot-during-rollback-window case) that re-runs `dhclient <target>` for any interface with an `inet dhcp` stanza that ifupdown2's own dispatch didn't bring up — scoped narrowly to interfaces the additive repair itself created, not a general-purpose fix, to avoid silently masking a genuinely different problem on some other interface.

## Whether Gates B–F may begin

No. Gate A has a real, independently-verified apply-time pass now (a first), but reboot-persistence — one of its own stated criteria — fails, confirmed directly rather than theorized.
