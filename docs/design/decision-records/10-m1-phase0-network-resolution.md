# Decision record: Milestone 1 Phase 0 — destination-network resolution

Date: 2026-09-21
Investigator: Claude Code
Status: complete. **Gate A does not pass. Result: `networking_unresolved`, with strong root-cause evidence and two distinguished-but-unresolved candidate causes.** Per the Milestone 1 plan's own rule, this is a blocking outcome — no Milestone 1 production module has been or may be written on the strength of this result.

## Scope discipline

Used only the disposable sparse-image/QEMU environment and existing non-interactive permissions, reusing Investigation 3's proven pipeline (`credential.py`, `answer_server.py`, `wrapper.py`, `workspace.py`, `preflight.py`, all reused via symlink, unmodified) and Investigation 6's QEMU-monitor screendump/keystroke helper (`vnc_type.py`, copied unmodified). No sudo, pkexec, polkit, or any privileged host interface was invoked or attempted. No physical device was touched. Two full install-boot-login cycles were run inside disposable QEMU guests; one credential-generation-only harness bug (a MAC mismatch between the answer server's expected hardware fact and the QEMU launch flags, entirely this investigation's own error, not a networking finding) caused one aborted install attempt, corrected without consuming an additional "rerun" from the plan's budget since it never reached installation.

## Evidence collected

### 1. Reproduction (unmodified pipeline)

A fresh sparse-image install via the exact proven pipeline reproduced the previously-observed result on the first attempt: after `Finished: 'ok'` / `Installation done` (captured directly, not inferred) and a disk-first reboot (`-boot order=c,once=d` working correctly), the login banner read:

```
https://[fec0::5054:ff:feba:5e12]:8006/
```

### 2. Full-layer capture, from inside the guest

- **Kernel command line**: `BOOT_IMAGE=/boot/vmlinuz-7.0.2-6-pve root=/dev/mapper/pve-root ro quiet` — no networking-relevant boot parameters.
- **Addresses** (`ip -o addr show`): `vmbr0` had **only** IPv6 addresses (`fec0::5054:ff:feba:5e12/64 scope site`, plus the standard `fe80::.../64` link-local) — **no IPv4 address anywhere**, not even on `lo` beyond `127.0.0.1`.
- **Routes**: no IPv4 route table entries at all; IPv6 default route `default via fe80::2 dev vmbr0`.
- **`/etc/network/interfaces`**: a fully **static** configuration —
  ```
  iface ens3 inet6 manual
  auto vmbr0
  iface vmbr0 inet6 static
          address fec0::5054:ff:feba:5e12/64
          gateway fe80::2
          bridge-ports ens3
          bridge-stp off
          bridge-fd 0
  ```
  No `inet dhcp` stanza, no `inet` stanza of any kind — this is not "DHCP client configured, IPv6-preferred," it is a **hardcoded static config with no live DHCP client running on the installed system at all.**
- **Active networking implementation**: `systemctl is-active` showed `systemd-networkd` and `NetworkManager` both **inactive**; `networking` (the `ifupdown2`-backed service) **active**. `systemctl is-enabled` showed `systemd-networkd` **disabled**, `NetworkManager` **not-found** (not installed at all), `networking` **enabled**. `dpkg -l` confirmed only `ifupdown2` (3.3.0-1+pmx12) is installed among networking-implementation packages. **This directly resolves the PRD's previously-unverified NetworkManager assumption (§5.12/§11): NetworkManager is not present on this Proxmox install at all; `ifupdown2` is the real, sole networking implementation.**
- **DNS**: `/etc/resolv.conf` contained `search invalid` and `nameserver 192.168.100.1` — a nameserver address on a subnet (`192.168.100.0/24`) with no relationship to SLIRP's actual internal network (`10.0.2.0/24`), and a search domain literally named `invalid`. Neither value corresponds to anything real in this environment. No DHCP lease files exist anywhere (`/var/lib/dhcp*`, `/run/systemd/netif/leases/*` both empty) — confirming no DHCP client of any kind is running on the installed system.
- **Contrast with the installer's own live environment**: Investigation 3 already established that the installer's live pre-install environment successfully obtained a real, working IPv4 DHCP lease from SLIRP (needed to reach the `guestfwd`-forwarded answer server at all — the install could not otherwise have succeeded). This confirms the missing-IPv4 problem is specific to what the installer **persists** onto the installed disk, not a SLIRP-wide inability to hand out IPv4 addresses.

### 3. Root-cause narrowing — a controlled, single-variable test

**Hypothesis**: SLIRP offers both a working IPv4 DHCP lease and continuous IPv6 router advertisements (a known SLIRP characteristic: it advertises the deprecated RFC 3879 site-local `fec0::/64` prefix by default); the installer's `from-dhcp` network-detection step, when constructing its `vmbr0` bridge configuration, captures whichever address family it observes and in this environment ends up capturing the IPv6 SLAAC-derived address instead of the IPv4 lease.

**Test performed (the one corrected rerun used)**: added `ipv6=off` to the QEMU SLIRP `-netdev user` configuration — the single smallest change that isolates address-family availability without touching the answer file, the installer, or any Baseline-authored code. Reran the identical pipeline.

**Result — hypothesis partially confirmed, but not in a way that produces usable networking**:
- With IPv6 disabled, the installer's own live environment showed, directly in its console output: a normal working ISC DHCP client negotiation (`DHCPDISCOVER` → `DHCPOFFER of 10.0.2.15 from 10.0.2.2` → `DHCPACK` → `bound to 10.0.2.15`), and a **cleanly failing** IPv6 router solicitation (`Sending ICMPv6 packet: Cannot assign requested address`) — confirming `ipv6=off` was applied correctly and IPv4 was the only available path.
- The resulting installed system's `/etc/network/interfaces` now contained a **different static IPv4 configuration**:
  ```
  iface vmbr0 inet static
          address 192.168.100.2/24
          gateway 192.168.100.1
  ```
  **This is not the real SLIRP-assigned lease (`10.0.2.15`).** `192.168.100.0/24` does not correspond to any real subnet SLIRP serves in this environment (SLIRP's internal network is `10.0.2.0/24`). This value is consistent with a Proxmox-installer-side default/fallback network used when the installer's bridge-construction logic cannot cleanly transplant the live-obtained DHCP lease onto the bridge it creates — **stated as a plausible, evidence-consistent explanation, not independently re-verified against Proxmox's own installer source this pass** (the reviewed `pve-installer` source excerpts from Investigation 2 did not cover this specific code path).
  - A residual, unexplained `fec0::5054:ff:feba:5e12/64 scope link proto kernel_ll` IPv6 address was still visible on `vmbr0` in this run despite `ipv6=off` and despite no IPv6 stanza appearing anywhere in `/etc/network/interfaces` — its exact source (a leftover install-time artifact, a kernel-level address unrelated to the disabled SLIRP RA, or something else) was **not chased further**, consistent with the instruction to keep this phase narrow; it does not change the conclusion below, since the IPv4 result already failed independently.
- **Direct connectivity test** (the actual required verification, not inferred from configuration alone): `ping 192.168.100.1` (the configured gateway) — **100% packet loss**. `ping 10.0.2.2` (SLIRP's real gateway) — **100% packet loss** (the interface has no route to it; wrong subnet entirely). `curl http://10.0.2.2/` — **`Failed to connect ... port 80 after 2312 ms: Could not connect to server`, `HTTPCODE=000`**. **All three failed cleanly and within a bounded time (~1–2.3s each), not by hanging** — this is a real, fast, unambiguous negative result, not an inconclusive one.

Given this, the five-property verification (address / route / DNS / outbound HTTPS / reboot-persistence) **was not pursued past outbound HTTPS**, since it had already failed decisively — testing reboot-persistence of a configuration already confirmed non-functional would add no information, consistent with the instruction to capture only the frames needed to prove the outcome.

## Result

**Two concrete, now-distinguished root causes remain, and this investigation's one-rerun budget was fully used reaching this point:**

1. **The address-family-selection layer** (why IPv6 vs. IPv4 gets captured) — addressed directly by this investigation's test: disabling IPv6 at the QEMU level does force IPv4 selection, confirming SLIRP's simultaneous IPv6 RA availability is at least part of what causes the original IPv6-only result.
2. **The bridge-transplant layer** (why *neither* captured address is actually usable) — **not addressed by this investigation's one permitted correction**, and is the more fundamental problem: even with IPv4 successfully selected, the value written to disk (`192.168.100.2/24`) does not match the real, working lease (`10.0.2.15`) the installer's own live environment demonstrably obtained moments earlier. Something in the installer's own from-dhcp-to-static-bridge-config logic is not correctly transplanting the live-negotiated address, independent of which address family is involved.

**Root cause is identified with direct evidence for layer 1. Layer 2 — the actual blocker for usable networking — is identified but not resolved**, and testing a fix for it (e.g., an explicit static-IP answer-file field instead of `from-dhcp`, or investigating Proxmox's own bridge-construction source further) would require a second installation rerun this investigation's budget does not cover without further authorization.

## Remaining uncertainty

- Whether `192.168.100.0/24` is genuinely a Proxmox-installer hardcoded default (plausible, consistent with the evidence, not confirmed against source).
- The exact origin of the residual `fec0::/64` address in the IPv6-disabled run.
- Whether a static (non-`from-dhcp`) answer-file network configuration would produce usable networking — this is the most promising next test and was **not** run, since it constitutes a second corrected-installation rerun beyond this investigation's authorized budget.
- Whether this is a QEMU/SLIRP/bridge-specific artifact or would also occur against a real DHCP server on real hardware — genuinely unknown; nothing in this investigation's evidence rules out either possibility, and per the PRD's own standing discipline (established across every Milestone 0 investigation), this must not be assumed to generalize to real hardware without a real-hardware test.

## Accepted / rejected approach

**Not accepted**: `network.source = "from-dhcp"` as currently used cannot be relied on to produce usable installed-system networking in this test environment, in either address family tested. **Rejected as a sufficient fix**: disabling IPv6 alone (tested directly, confirmed insufficient — trades one non-functional address for another). **No approach is accepted yet** — this investigation's job was to determine root cause and test the smallest plausible correction, not to exhaust every option; a further, explicitly-authorized test (most likely: an explicit static IPv4 answer-file configuration, bypassing `from-dhcp`'s bridge-transplant logic entirely) is the recommended next step, not decided here.

## Security implications

None directly — this is a functionality/architecture finding, not a security one. Indirectly relevant to the PRD: any design that assumed `from-dhcp` produces a live, renewing DHCP client on the installed system (relevant to §5.12's tether/network preconfiguration assumptions) is now known to be wrong — the installed system has no DHCP client running at all, of any kind, under the configuration tested.

## Tests added

None as portable code — this was a live, disposable-environment investigation, per Phase 0's own instruction not to build production modules or a new test framework. The two QEMU invocation variants (baseline vs. `ipv6=off`) are recorded verbatim above and are the concrete starting point for whatever Milestone 1 code eventually needs to reproduce or test around this.

## Artifacts retained or deleted

Per the Milestone 1 plan's retention rules (§9/§7 of the v2 plan): both one-time plaintext credentials and their answer-file/hash content were deleted after use, confirmed absent from every retained log via direct grep before deletion. Both prepared ISOs and both 7.1GB sparse target images were deleted after their evidence was captured. Raw `.ppm` screendumps were deleted, keeping only the converted `.png` evidence images and small text logs. Total retained evidence: **288KB** across both run directories (`experiments/m1-phase0/runs/`, gitignored, not committed) — screenshots and logs only, no secret material, confirmed by direct grep before cleanup.

## Whether Milestone 1 (Gates B–F) is unblocked

**No. Gate A does not pass.** Per the Milestone 1 plan's explicit rule, `networking_unresolved` is a blocking outcome, not an alternative way to satisfy Gate A. No production module in the plan's §4 may be started. The decision to authorize a further, explicitly-scoped test (most concretely: one more install using a static IPv4 answer-file configuration instead of `from-dhcp`, to test whether that bypasses the bridge-transplant problem) or to accept a different resolution path is handed back to the user, per Phase 0's own instruction, rather than decided unilaterally here.
