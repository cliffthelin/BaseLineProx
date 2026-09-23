# Decision record: Gate A fully passes — apply-time and reboot-persistence, first in this project's history

Date: 2026-09-22
Investigator: Claude Code
Status: **Gate A fully passes.** The additive repair pipeline (`repair_additive.add_dhcp_to_bridge`), run against a directly-staged, byte-exact reproduction of Fixture A, achieves a full apply-time pass — address, route, gateway, DNS, and HTTPS all independently confirmed working — for the first time in this project's history. The reboot-persistence gap this same investigation found and confirmed directly (below) was then closed with a new, narrowly-scoped boot-time systemd unit (`baseline-additive-dhcp-reapply.service` + `repair_additive_persist.py`), unit-tested (6 new tests, 87/87 total) and independently re-verified in a second real QEMU run: after a clean reboot, address, route, gateway, DNS, and HTTPS all pass again, automatically, with no manual intervention. **This is the first time Gate A has fully passed in this project's history.**

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

## The reboot-persistence fix: `repair_additive_persist.py` + `baseline-additive-dhcp-reapply.service`

Matching the precedent already named as unbuilt in `repair_rollback.py`'s own module docstring for the reboot-during-rollback-window case, a new, narrowly-scoped boot-time systemd unit was written:

- `baseline/lib/repair_additive_persist.py` — `reapply_additive_dhcp(runner)`. Reuses `repair.read_interfaces_config` (unchanged) to parse the live config, then scopes strictly to interface names `ifnet_config`'s own parser already recorded in `duplicate_names` **and** where a second, separate `iface <name> inet dhcp` stanza specifically exists (a regex match against the raw config text, not just "this name is a duplicate for any reason") — deliberately not a general-purpose "retry DHCP on anything" tool, to avoid silently masking a genuinely different problem on some other interface (e.g. a hand-edited file with two conflicting static stanzas, which this must not touch). For each match, checks `ip -4 -o addr show dev <name>` first and only runs `dhclient <name>` when no IPv4 address is already present — idempotent, safe to run on every boot, a no-op on the overwhelming majority of boots once a lease is held.
- `baseline/bin/baseline-additive-dhcp-reapply` — thin installed entry point, matching the existing `baseline-repair-rollback` pattern exactly.
- `boot/baseline-additive-dhcp-reapply.service` — `Type=oneshot`, `After=networking.service`, `WantedBy=multi-user.target`.
- Wired into `provision.sh` alongside the existing repair modules.

Unit-tested first, per this project's established discipline (`tests/unit/test_repair_additive_persist.py`, 6 new tests, all `FakeRunner`-scripted): reapplies when the additive signature is present and no IPv4 address exists; no-ops when an address is already present; no-ops for a non-additive config; does not touch a duplicate name that isn't an additive-dhcp shape (the two-static-stanzas case); records a `fail` event and correct detail on a `dhclient` failure; idempotent on a second run once an address exists. 87/87 total unit tests passing.

**Then independently re-verified for real**, not just unit-tested: a second disposable QEMU install (`gateAv7b`), same Fixture A staging methodology, additive repair applied (`outcome: "success"`, same as before), the new systemd unit deployed and enabled, then a real `reboot` (clean, not forced). After reboot: `ip -4 addr show vmbr0` → `inet 10.0.2.15/24 ... dynamic vmbr0`; `ip -4 route show` → `default via 10.0.2.2 dev vmbr0`; `getent hosts deb.debian.org` resolved; `wget https://deb.debian.org/` → `HTTPS_OK`. All five properties, automatically, with zero manual intervention — `systemctl status baseline-additive-dhcp-reapply.service` confirms `status=0/SUCCESS` and the journal shows exactly the expected `[pass] vmbr0: boot-time reapply: dhclient vmbr0` line.

## What this means for Gate A

Gate A's stated criteria are: Fixture A produces a bounded additive proposal (existing unit tests); declining makes no change (existing unit tests); concurrent edits refuse (existing unit tests); failed DHCP restores exact original (existing unit tests); successful DHCP verifies address/route/gateway/DNS/HTTPS (confirmed directly, this record); config remains functional across reboot (confirmed directly, this record, after the fix above). **Every stated criterion now has direct, real evidence behind it.**

## Whether Gates B–F may begin

**Yes.** Gate A fully passes — the first time in this project's history — with both apply-time and reboot-persistence independently verified against real QEMU, real ifupdown2, real dhclient, real SLIRP. The separately-unresolved guestfwd infrastructure problem (decision record 16) still blocks the *automated/answer-file* install path specifically, and should be kept in mind for any future work that depends on that path (e.g. building a fresh disposable image from scratch without manual TUI interaction) — but it does not block Gate A itself, since this investigation found and validated a working route around it.
