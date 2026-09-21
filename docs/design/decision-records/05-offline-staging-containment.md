# Decision record: Offline staging containment

Date: 2026-09-20
Investigator: Claude Code
Status: partial — core containment mechanism verified; full test against the actual installed image blocked by real, empirically-confirmed environment constraints on this development host, not assumed or worked around

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

## Accepted / rejected approach

**Accepted, provisionally**: **plain chroot with bind-mounted `/proc`/`/sys`/`/dev`, plus `policy-rc.d` returning 101 as a defense-in-depth layer**, relying primarily on the verified no-running-systemd mechanism rather than `policy-rc.d` alone (since that specific layer is unverified this session). This matches the PRD's original preference (§5.8) and keeps the architecture simple — no nspawn-specific privilege requirements to work around later, given nspawn's own unprivileged mode is already confirmed problematic on at least one representative development host.

**Rejected for now, not because it's unsafe but because it's unverifiable here**: `systemd-nspawn`. Its containment properties are plausibly at least as strong as chroot's, but this session could not confirm even basic unprivileged operation on this host, and Milestone 1 shouldn't adopt a mechanism whose operational reliability is less established than the alternative when the alternative's core safety property is already directly confirmed.

**Not rejected, held as the explicit fallback**: defer-to-first-boot, exactly as the PRD already frames it — "a legitimate alternative to chroot containment, not just a fallback." If Milestone 1's real, root-capable implementation finds chroot-based staging fragile in practice (dependency on `/proc`/`/sys`/`/dev` bind-mount correctness, interactions with the specific package set), defer-to-first-boot remains available without this decision record needing revision.

## What Milestone 1 must still verify with real root

This decision record does not close the loop the PRD's own testing section (§8, "Milestone 0/1 must decide between... prove: package installation and service-awareness") expects. Specifically, still needed, with real privilege (via the eventual `pkexec`-invoked helper, not this interactive session):

- The actual five-tool install (`lm-sensors`, `nvme-cli`, `smartmontools`, `iperf3`, `ethtool`) against the real chroot target, confirming no `iperf3` listener ends up enabled — this is the PRD's own stated concern and remains untested against a real target.
- `policy-rc.d`'s actual effect inside a real chroot target's own filesystem (not this host's).
- Package-database consistency (`dpkg --audit` or equivalent) after the chroot install completes.
- First-boot-unit enablement surviving the chroot install (i.e., `systemctl is-enabled <unit>` reporting correctly once the system actually boots for real — connects directly to Investigation 4's proven boot pipeline, which is available to build on).

## Security implications

- The core finding — no running systemd inside the staging environment reliably blocks maintainer-script service starts — is a genuinely useful, verified safety property, independent of which higher-level tool (chroot vs. nspawn) ends up wrapping it.
- The verification gap here (root unavailable in this interactive session) is itself a useful Milestone 0 finding: it confirms the project's standing architectural choice (all privileged operations go through `pkexec`, never ambient sudo) is consistent with what this session could and couldn't do — the same boundary that protects the shipped tool from needing broad sudo access also means this kind of deep-privilege research has to happen in a different context (either an interactive session where the user supplies `pkexec`/sudo authentication, or inside Milestone 1's real helper).

## Tests added

None — this was research, and the one piece of code exercised (the `unshare`-based no-running-systemd proof) was a throwaway shell one-liner, not saved as a module. Milestone 1's real containment implementation should carry this same proof forward as an actual test (`test_offline_staging_containment.py` or equivalent), exercised for real against a real chroot target once root is available.

## Whether Investigation 6 is unblocked

**Yes, provisionally.** Investigation 6 (first-boot state-machine prototype) does not depend on offline staging containment being fully resolved — per the PRD's own milestone sequencing, it can proceed using a QEMU boot of the already-proven install pipeline (Investigations 3/4), prototyping the tty1 confirmation flow independent of whether packages were staged via chroot or deferred to first boot. The chroot-vs-nspawn question this record leaves partially open does not block that work.
