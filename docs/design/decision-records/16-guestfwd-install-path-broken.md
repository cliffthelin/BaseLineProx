# Decision record: the QEMU guestfwd answer-file path is currently broken on this host — blocks fresh disposable installs

Date: 2026-09-22
Investigator: Claude Code
Status: root cause not found; conclusively demonstrated as real, reproducible, and independent of both host load and `restrict=on`. **This blocks building any new disposable Proxmox install on this host via the established guestfwd/ephemeral-answer-server methodology (decision records 10-15's own installs, and the `gateAv4_prep.py`-derived pattern reused here). It does not affect or walk back decision record 15's DHCP-router-option finding, which used an already-installed guest and never depended on guestfwd.**

## Scope discipline

No push to `cliffthelin/baseline`. No physical device. No host package installation or removal. No privilege escalation (packet capture via `tcpdump` was attempted and refused for lack of `CAP_NET_RAW`; not worked around). No authorization-triggering host call. Four disposable QEMU install attempts (`experiments/m1-gateA-v4/runs/gateAv5-*`, `gateAv5b-*`, `gateAv5c-*`, `gateAv5d-*`), all cleaned up per retention policy (canary-leak grep before deletion, each workspace reduced to under 260KB of logs/screenshots/state).

## Original goal

Decision record 15 left one explicitly open question: whether `-netdev user,restrict=on` (used for every disposable install in this project) was the reason QEMU/SLIRP's built-in DHCP server never sent a `routers` option. Testing this required building a fresh disposable install both with and without `restrict=on`, since the existing installed disk image had already been deleted per retention policy after decision record 15's own workspace was cleaned up.

## What happened instead: every fresh-install attempt failed before reaching that question

### Attempt 1 (`gateAv5`, `restrict=on`)

Failed with kernel soft lockups and an answer-file HTTP timeout. At the time, `uptime` showed load average 329 on a 24-core host (~14x oversubscribed, from unrelated processes: heavy `ntfs-3g` disk I/O, an `invokeai-web` process, VS Code, snapd). Reasonably attributed to host contention at the time and reported as such.

### Attempt 2 (`gateAv5b`, `restrict=on`, host load confirmed normal: 0.87/1.15/1.05)

Failed identically: `INFO: Sending POST request to 'https://10.0.2.100:8443/answer/...'` followed immediately by `INFO: Fetching answer file via HTTP failed: timeout: global` and `ERROR: Aborting: Could not find any answer file!`. Host load was normal this time — ruling out load as the explanation.

Directly tested the answer server itself from the host (bypassing the guest and guestfwd entirely): `curl -sk -X POST https://127.0.0.1:<port>/answer/<session>` returned in 2ms with `403 already consumed` — proving the server had, at some point, already received and fully processed a POST for that exact session (the installer's own attempt), marking it consumed. This is the key clue: the guest's request evidently *did* reach the server and *was* processed, but the installer itself never received a usable response back in time.

### Attempt 3 (`gateAv5c`, `restrict=on`, host load normal)

Failed identically a third time. This time, instead of letting the install self-abort and moving on, used the guest's own post-abort rescue shell (still running, network stack still up) to test connectivity manually:

- `curl`: not present in this minimal installer environment.
- `nc -zv`: this BusyBox `nc` build doesn't support `-z` (printed usage instead of connecting).
- `openssl s_client -connect 10.0.2.100:8443 -quiet < /dev/null`: **hung with zero output.** Interrupted manually after `real 1m25.459s` (`^C`, confirmed via `time`).
- Ran the identical command again immediately after: hung again, still no response after 100+ seconds, never resolved on its own — not a one-off, not eventually-successful-but-slow.

This is direct, unambiguous evidence: TCP-level connectivity from inside the guest to the guestfwd-mapped target address (`10.0.2.100:8443`) is not reliably completing, independent of the HTTPS/TLS layer, independent of the answer-server's own logic (confirmed responsive and correct from the host side), and independent of host load (confirmed normal throughout this attempt).

### Attempt 4 (`gateAv5d`, **no** `restrict=on`, host load normal)

Removing `restrict=on` did visibly change guest behavior in two ways: `trying to detect country...` now resolved (`detected country: US`, previously always timed out), and a detailed IPv6 router-advertisement dump appeared during the DHCPv6/SLAAC phase (hop limit, prefix `fec0::/64`, lifetimes, source link-layer address) that hadn't printed with `restrict=on` on. This confirms `restrict=on` does suppress/alter more of SLIRP's guest-visible network behavior than previously scoped in decision record 15 (which only looked at the DHCPv4 `routers` option).

**But the guestfwd answer-file fetch failed in exactly the same way, with `restrict=on` removed entirely**: same `timeout: global`, same abort. The follow-up manual `openssl s_client -connect 10.0.2.100:8443` test hung identically to attempt 3.

**This conclusively separates the two problems**: whatever is breaking guestfwd connectivity is not `restrict=on` — it reproduces with `restrict=on` on and off, under normal host load, across four independent fresh QEMU instances. Decision record 15's original open question (does removing `restrict=on` restore the DHCP `routers` option) remains untested, because no attempt has gotten far enough into a full install for that specific check to be reachable — the earlier, unrelated guestfwd failure aborts the install first, every time.

## What was ruled out

- **Host load**: confirmed normal (load average under 1.2 on 24 cores) for attempts 2-4; the failure reproduced identically regardless.
- **`restrict=on`**: confirmed the failure reproduces with it both present and absent.
- **Answer-server logic**: confirmed correct and fast (2-3ms) when queried directly from the host, bypassing the guest.
- **Stale QEMU/socket state**: checked for stray QEMU processes or leftover listeners before each retry; none found. Each attempt used a fresh workspace, fresh session ID, and fresh ephemeral TLS keypair reuse (same cert, standard for this harness) — not a session-ID collision or reused-state artifact.
- **A recent package regression, as the obvious first guess**: checked `/var/log/apt/history.log` and the installed `qemu-system-x86`/`libslirp0` changelogs for anything guestfwd/SLIRP-networking-relevant. Found only an unrelated virgl-crash and iothread-race point release; nothing in the changelog entries touches SLIRP or guestfwd. This doesn't rule out a regression, but no direct evidence supports one either — reported as inconclusive, not negative.

## What was not attempted, and why

- **Packet capture** (`tcpdump -i lo`) to see exactly what happens at the TCP level: refused immediately with `CAP_NET_RAW may be required` — this host user has no capability to capture packets without `sudo`/`setcap`, which is privilege escalation and off-limits per this project's standing rules.
- **Downgrading or reinstalling `qemu-system-x86`/`libslirp0`** to bisect a possible regression: would be a host package management operation, off-limits per this project's standing rules without explicit authorization.
- **A host reboot** to rule out accumulated kernel/network-stack state (e.g., from the load spike in attempt 1): a real, plausible fix, but rebooting the user's development machine is a disruptive action requiring the user's own decision, not something to do unilaterally mid-session.

## What this means

This is a **host/environment infrastructure problem**, not a defect in this project's own code (`repair.py`, `repair_additive.py`, `ifnet_config.py`, `topology.py` are untouched by and unrelated to this finding) and not a regression introduced by any change made in this session. It does, however, block a real capability this project depends on: building a fresh disposable Proxmox install for any future Gate A/B-F QEMU-based verification work. Every prior successful disposable-install decision record in this project (10 through 14, and the install that originally produced the disk image decision record 15 later reused) necessarily happened before whatever is now causing this — the exact point in time it started is not established.

Decision record 15's core finding (SLIRP's DHCP server doesn't send a `routers` option) is unaffected by this — that investigation used an already-installed guest booted directly, with no guestfwd involved. This decision record's open question about `restrict=on`'s effect on that specific finding remains genuinely untested, and is now understood to require first resolving this guestfwd problem before it can be tested at all.

## Recommended next steps for whoever picks this up

1. A host reboot is the single most likely fix worth trying first, given attempt 1's severe load spike immediately preceded the first observed failure — but this is the user's call, not something to do unilaterally.
2. If the problem persists after a reboot, packet capture (with the user's own elevated access, not this session's) on the host loopback interface during a repro attempt would directly show whether the guest's SYN/response ever reaches or leaves 127.0.0.1 at all.
3. Consider testing the same guestfwd pattern against a plain, minimal QEMU guest (not a full Proxmox installer environment) to isolate whether this is installer-specific or a general guestfwd problem — this session attempted a lighter-weight version of this (direct kernel boot with a custom busybox initramfs) but was blocked because the host kernel image is root-only readable; a small pre-built cloud image or ISO with looser permissions would sidestep that.

## Whether Gates B-F may begin

No, unchanged from decision record 15. Additionally: no NEW disposable Proxmox install can currently be built on this host at all, which further blocks any future work that would require one (this is a broader statement than Gate A specifically).
