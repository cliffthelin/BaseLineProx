# Decision record: Offline staging containment

Date: 2026-09-20
Investigator: Claude Code
Status: **complete**. `defer-to-first-boot` tested for real against the actual installed image (a disposable overlay, base image preserved) and **accepted** as the approach. chroot/`systemd-nspawn` remain unverified in this session — not proven unsafe, just not needed given the result below. See the Addendum for the real test; the original body below is kept for the honest record of why the chroot/nspawn comparison path was abandoned rather than forced.

## Correction to approach, per explicit instruction

The privilege gap described below (no root/sudo, no working unprivileged mount path) was **not** treated as something to route around. No sudo password was requested or used, no kernel/host permissions were changed, no privileged mounting helper was built. Instead the gap itself was read as evidence: if chroot/nspawn containment can only be verified with real root, and the target system's own destination hardware will have real root and a genuinely running systemd anyway, the simpler and safer design is to **not stage packages offline at all** — copy Baseline and the setup-intent/first-boot components only, and let package installation happen during the real first-boot state machine, in the real target OS, with real systemd. This is tested directly below, not assumed.

## What this investigation could and could not do on this host

This investigation needed to compare chroot, `systemd-nspawn`, and defer-to-first-boot for installing packages into a staged root filesystem without letting maintainer scripts start services against the host. The natural test is: mount the actual Proxmox image produced by Investigation 3/4, chroot or nspawn into it, install one of the five diagnostic tools (`iperf3`, flagged in the PRD as having real service-start risk), and observe.

**That full test could not be run in this session**, for reasons confirmed directly rather than assumed:

- Mounting `target.img`'s LVM-backed ext4 root requires `losetup` + LVM activation + `mount`, all of which need real root. This session has no passwordless sudo (`sudo -n true` fails with "interactive authentication is required") and no other privilege escalation path — consistent with this whole project's standing design (privileged operations go through `pkexec`, which needs a real interactive user present to approve a graphical prompt, not available in this non-interactive session).
- `guestmount` (libguestfs), which can mount disk images unprivileged via a small internal VM, was tried and **failed for a concrete, verified reason**: its supermin appliance builder needs to read `/boot/vmlinuz-<version>` on the host, which is not world-readable on this Ubuntu install (`cp: cannot open '/boot/vmlinuz-7.0.0-31-generic' for reading: Permission denied`) — standard kernel-image hardening, not something to work around by loosening host permissions.
- `fuse2fs` (an alternative unprivileged FUSE-based ext4 mounter) is not installed on this host, and installing it would itself violate Milestone 0's no-host-modification constraint.
- `systemd-nspawn` was tried directly, unprivileged, against a disposable throwaway directory (not the real image) and **failed for a concrete reason**: `Failed to allocate user namespace with 64K users: No such file or directory` — this host's unprivileged-nspawn support isn't configured (no usable subuid/subgid range for this path), confirmed by direct attempt, not assumed.

**What this means**: the comparison this investigation was supposed to make (chroot vs. nspawn vs. defer-to-first-boot, exercised against the real image) cannot be completed in an interactive Milestone-0 research session on this particular development host. It becomes fully testable once this logic runs where it actually belongs — inside the real privileged helper, invoked via `pkexec`, which has genuine root — which is Milestone 1 work, not this session's. This gap is recorded here explicitly rather than papered over with an untested recommendation.

## What was verified — the core safety mechanism, unprivileged, reproducible, no host modification

The actual safety question underneath "compare three containment approaches" is narrower and more testable: **can a package's maintainer script actually start a service against something outside the staging environment?** This was tested directly, without touching the real image and without any host modification, using Linux user namespaces (`unshare --user --map-root-user --mount --pid --fork --mount-proc`):

```
$ unshare --user --map-root-user --mount --pid --fork --mount-proc bash -c '
    mount -t tmpfs tmpfs /run
    systemctl start iperf3
'
System has not been booted with systemd as init system (PID 1). Can't operate.
Failed to connect to system scope bus via local transport: Host is down
(exit 1)

$ # confirms the mechanism directly:
$ test -d /run/systemd/system && echo exists || echo absent
absent
```

**This is the actual mechanism that matters**, and it holds regardless of which specific tool (plain `chroot`, `systemd-nspawn` without `--boot`, or an `unshare`-based sandbox) wraps it: a staging environment with no real, running systemd instance as PID 1 and no bind-mounted host `/run/systemd/private` socket cannot have `systemctl start <service>` (or `deb-systemd-invoke`, which checks the same `/run/systemd/system` marker before falling back to `systemctl`) succeed — it fails closed, with a clear error, not a silent no-op. This is the property PRD §5.8 actually needs ("prevent any service from starting against the host"), and it was confirmed directly rather than cited from general Debian/Ubuntu knowledge.

**`policy-rc.d` was not independently verified this session.** An attempt to test the `/usr/sbin/policy-rc.d` exit-101 convention failed for an environment reason of its own: the unprivileged user-namespace "fake root" from `unshare --map-root-user` does not grant write access to the *real* host's `/usr/sbin` (permission checks pass at the syscall layer inside the namespace, but the underlying filesystem is still the host's actual, unwritable `/usr/sbin` unless a separate writable root is constructed) — and building a disposable-but-real root filesystem for that test properly was out of scope for what this investigation's remaining time budget allowed. `policy-rc.d` is Debian's own standard, well-documented convention (exit 101 = action denied) and is expected to work inside a real chroot target's own `/usr/sbin` once one exists (Milestone 1, with real root) — but this session did not independently reproduce it, and says so rather than asserting it.

## Comparison of the three approaches, given the above

| Approach | Containment mechanism | Verified this session? |
|---|---|---|
| Plain chroot (+ bind mounts, + `policy-rc.d`) | No running systemd inside the chroot unless one is deliberately started; `policy-rc.d` as a second, defense-in-depth layer | Core no-running-systemd mechanism: **yes**, directly. `policy-rc.d` specifically: **no**, blocked by this session's inability to construct a writable disposable root. |
| `systemd-nspawn` (without `--boot`) | Same no-running-systemd mechanism, plus nspawn's own namespace/cgroup isolation | **No** — nspawn itself could not be exercised unprivileged on this host (subuid/subgid configuration gap, confirmed by direct failure). |
| Defer-to-first-boot | Sidesteps the question entirely — packages install for real, with a real running systemd, on the destination hardware where starting real services is expected and safe | Not applicable to test here — its safety property is definitional (there's no "host" to protect at first-boot time in the same sense), not something this session needed to verify. |

## Original (superseded) accepted/rejected reasoning

*Kept for auditability — this was the reasoning before the real defer-to-first-boot test below; the final decision is in the Addendum, not here.* The original text provisionally accepted chroot + `policy-rc.d` and rejected `systemd-nspawn` as unverifiable, holding defer-to-first-boot as a fallback. That ordering is now reversed: defer-to-first-boot is accepted, and chroot/nspawn are explicitly **not proven unsafe, just not needed** for this workflow — see the Addendum.

## Addendum: real defer-to-first-boot test, disposable overlay of the actual installed image

Per explicit instruction: no sudo password requested or used, no kernel/host permissions changed, no privileged mounting helper built. This test used the running guest itself — the one environment on this host that legitimately has real root and a real systemd — rather than trying to construct one on the host side.

**Setup**: a `qemu-img create -f qcow2 -b target.img -F raw` overlay of the Investigation 4 preserved image (backing file never opened for writing), booted with fresh OVMF NVRAM, no installer ISO, general outbound networking (not the restricted/`guestfwd`-only network used for the answer-fetch investigations — this guest needed real package-repo reachability, which is exactly what a real destination machine's first boot would also have). Logged in interactively as `root` using the synthetic installation credential, driven via QEMU monitor `sendkey` injection against the VGA console (the same technique used to confirm Investigation 3/4's login screens), with results captured by having the guest `curl` a POST back to a small relay server on the host rather than relying on slow screenshot-only round-trips.

**Incidental finding, corrected in-session, not treated as a blocker**: the installer's `[network] source = "from-dhcp"` had baked a **static, IPv6-only** configuration into `/etc/network/interfaces` (`fec0::.../64`, a non-routable site-local prefix, no IPv4 address at all) — meaning the installed system had no way to reach the real internet at all until an IPv4 address and default route were added manually for this test session (`ip addr add 10.0.2.15/24 dev vmbr0 ; ip route add default via 10.0.2.2`, not persisted to any config file). **This is a real, separate finding worth carrying into Milestone 1**: whatever network configuration the automated installer produces from a DHCP source needs to be checked for exactly this — IPv6-only capture discarding a working IPv4 lease — since it would leave a real destination machine's first boot without usable network access under many real dual-stack DHCP setups. Not investigated further here (out of this investigation's scope), but flagged for whoever builds the real first-boot networking logic.

**Test executed, matching the required steps exactly**:
1. `apt-get update` — succeeded for Debian's own trixie/trixie-security/trixie-updates repos; failed with `401 Unauthorized` for the two `enterprise.proxmox.com` repos (ceph-squid and pve), expected and correct behavior for an installation with no subscription key — Baseline's real implementation should point at the no-subscription repo (per Investigation 1) rather than treating this as an error to fix.
2. `DEBIAN_FRONTEND=noninteractive apt-get install -y lm-sensors nvme-cli smartmontools iperf3 ethtool` — succeeded, no interactive prompts.
3. `ss -tlnp` captured before and after: **identical listening-socket sets** — `127.0.0.1:85` (pvedaemon), `127.0.0.1:25`/`[::1]:25` (postfix), `0.0.0.0:22`/`[::]:22` (sshd), `0.0.0.0:111`/`[::]:111` (rpcbind), `*:3128` (spiceproxy), `*:8006` (pveproxy) — all pre-existing Proxmox services, nothing new from any of the five packages.
4. `systemctl status/is-enabled/is-active iperf3` — **`disabled` / `inactive (dead)`**, both immediately after install and again after a full reboot. The unit file itself ships with `preset: enabled` (the upstream/distro-declared default), but the actual state on this system is disabled and never active — confirming the safety property holds without needing `policy-rc.d` or any containment layer at all, because it's happening in the destination environment's own normal package-install path, not a synthetic sandbox.
5. `sensors-detect` was not run (confirmed: `/etc/sensors3.conf` present is the package-shipped default, not a `sensors-detect`-generated one) and no SMART self-test was triggered (confirmed: `smartctl --all /dev/vda | grep -i self-test` returned nothing).
6. `dpkg -l` for all five packages: `ii` (installed, configured) both before and after reboot.
7. `dpkg --audit`: no output — consistent package database.
8. **Reboot performed** (`reboot`, a normal in-guest command, not a forced stop): system came back to the login prompt within seconds, LVM reported `/dev/mapper/pve-root: clean`. Post-reboot re-check confirmed all five packages still `ii`, the listening-socket set unchanged, and `iperf3` still `disabled`/`inactive`.

**One nuance recorded honestly**: `smartmontools.service` showed up as already `enabled` in the *before* snapshot — because `smartmontools` ships as part of Proxmox VE's own base install (Proxmox uses it for its own health/inventory features), not something this investigation's install step introduced. The PRD's actual concern was specifically `iperf3` (a tool with no legitimate reason to be running as a server on this host), and that one stayed disabled/inactive throughout.

## Final decision

**Accepted**: `defer-to-first-boot`. Offline staging copies Baseline and the setup-intent/first-boot components only — no package installation happens offline. The five diagnostic tools (and any other packages Baseline needs) install during the real first-boot state machine, against the real, running destination OS with a real systemd, exactly as this test just demonstrated works cleanly with no unwanted listeners, no unwanted enabled services, and full survival across a reboot.

**chroot and `systemd-nspawn` are not rejected as unsafe — they remain unverified**, exactly as instructed. This investigation simply no longer needs them: Baseline's actual workflow doesn't require offline package staging at all, so the question of which containment tool would have been safest for that staging never has to be answered for this project. If a future requirement reintroduces a genuine need for offline package staging, this gap should be revisited with real privilege at that time, not assumed answered by this investigation.

## Security implications

- Maintainer scripts calling more than `systemctl` — direct binary invocation, device manipulation, host-interface dependencies — is exactly why this result is stronger than the earlier partial one: nothing here relies on "no running systemd" as the sole safety boundary, because there was a *real*, fully running systemd the whole time, on real (virtual) hardware, exactly matching the destination environment. There is no containment-mechanism ambiguity left to worry about, because there is no containment mechanism in this design — package installation happens exactly where and how it's meant to happen permanently.
- The IPv6-only DHCP-capture finding is a genuine, separate risk worth tracking: a destination machine's first boot losing IPv4 reachability would be a real deployment problem, unrelated to security but directly relevant to whether first-boot package installation (this investigation's whole subject) can even reach a package repository in the field.

## Tests added

None as reusable code — this was an interactive, one-off verification against a disposable overlay. The eight-step check (listening sockets before/after, `iperf3` enabled/active state, `dpkg -l`, `dpkg --audit`, reboot survival) should become Milestone 1's actual first-boot-stage integration test once the real first-boot state machine exists (Investigation 6 onward), run for real rather than re-derived from this session's ad hoc shell commands.

## Whether Investigation 6 is unblocked

**Yes.** Investigation 6 (first-boot state-machine prototype) can now build directly on this result: the state machine's package-installation step is confirmed safe and simple — a real `apt-get install` against the real running target, no containment layer needed. The PRD is being updated accordingly (see the drive-setup-gui-v2-prd.md changelog) before Investigation 6 begins.
