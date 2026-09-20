# Bare-Metal Bring-Up Notes

Practical gotchas from V0.1's first real bare-metal session (QEMU dev/test
build, then a physical Dell laptop). Organized by symptom so a future
session can jump straight to the fix. See also `docs/adr/0001-bare-metal-
network-bootstrap.md` for the two network findings written up in more
depth.

## Host/QEMU safety

**Symptom:** Pressed a VT-switch key combo (e.g. `Ctrl+Alt+F2`) inside a
QEMU GTK window expecting it to switch consoles *inside the guest* - it
switched the **host's own desktop** to a different virtual terminal
instead, requiring a host reboot to recover.
**Cause:** QEMU's GTK display doesn't grab function-key combos by default;
they go to the host X/Wayland session, not the guest.
**Fix:** Never use `Ctrl+Alt+F<n>` to try to reach a guest's other
consoles from a QEMU GTK window. If a guest console switch is genuinely
needed, do it from inside the guest's own session (SSH, or a tool that
explicitly targets the guest).

**Symptom:** A previously-correct `/dev/sdX` reference pointed at a
completely different, important drive after a reboot.
**Cause:** Linux device letters (`/dev/sda`, `/dev/sdb`, ...) are assigned
by enumeration order at boot and are **not stable** across reboots or
reconnects.
**Fix:** Always use `/dev/disk/by-id/...` (stable hardware-serial-based
paths) for any operation that matters - especially anything destructive.
Never assume a drive letter from an earlier session still points at the
same physical device.

**Symptom:** `/tmp` scratch files (including a generated SSH private key)
disappeared after a host reboot.
**Cause:** `/tmp` is cleared on reboot by design.
**Fix:** Keep anything that needs to survive a reboot (the actual repo,
generated keys you still need) on persistent storage, not `/tmp`.

## Proxmox / apt

**Symptom:** `apt-get update` fails with `401 Unauthorized` against
`enterprise.proxmox.com` repos.
**Cause:** Proxmox's default installed sources include the enterprise
repo, which requires a paid subscription.
**Fix:** `mv /etc/apt/sources.list.d/pve-enterprise.sources{,.disabled}`
(and `ceph.sources` if present) before doing anything else with apt.

**Symptom:** `apt-get install -y wpa_supplicant` fails with "Unable to
locate package".
**Cause:** The Debian **package** name is `wpasupplicant` (no underscore
between wpa and supplicant) even though the **binary** is
`wpa_supplicant`.
**Fix:** `apt-get install -y wpasupplicant`.

## Claude Code CLI

**Symptom:** `claude` (any subcommand, even `--help`) hangs indefinitely,
pinning a CPU core at ~99% with no output, no error.
**Cause 1:** Node.js version too old. Claude Code needs Node **>=22**;
Debian's own `nodejs` package (v20 on trixie) triggers this hang instead
of a clean version-mismatch error.
**Fix 1:** Install Node 22+ via NodeSource
(`curl -fsSL https://deb.nodesource.com/setup_22.x | bash -`, then
`apt-get install -y nodejs`), not the distro package.
**Cause 2 (under QEMU specifically):** The guest CPU model is missing
modern instruction set extensions (default QEMU CPU models are very
conservative). `strace` on the hung process showed ~93% of syscall time
in `futex` - a spin/livelock, not an I/O wait.
**Fix 2:** Launch QEMU with `-cpu host` to pass through the real host
CPU's feature set. (Not applicable on real bare metal - this is a QEMU
testing artifact only.)

**Symptom:** `claude setup-token`'s OAuth URL, once opened in a browser,
gives "invalid OAuth Request: unknown scope: user".
**Cause:** The URL got truncated in transit - usually a terminal
line-wrap during copy/paste, dropping the `%3Ainference` suffix off
`scope=user%3Ainference`.
**Fix:** Get the complete, unwrapped URL (e.g. run `claude setup-token`
under `tmux`/`script` and read the log file rather than eyeballing a
wrapped terminal) and open that exact string, fresh, in a new tab. A
stale/cached tab from an earlier attempt will carry the wrong `state`
value and get rejected even with a valid-looking code.

## Networking - DHCP client behavior

**Symptom:** `dhclient <iface>` prints `Error: ipv4: Address already
assigned` and does nothing further; the interface keeps a stale address
and no default route gets (re-)installed.
**Cause:** `dhclient` sees an existing address and skips the full
negotiation (including route installation) that a truly fresh lease would
do.
**Fix:** Don't try to negotiate around it - `ip addr flush dev <iface>`
first, then `dhclient <iface>` for a genuinely clean request.

**Symptom:** After `dhclient -r <iface>` (release), the interface has no
IPv4 address at all and stays that way.
**Cause:** `-r` only releases; it does not renew. The next `dhclient
<iface>` (no flags) step was skipped.
**Fix:** Release and renew are two separate commands - always run both,
or just use the flush approach above instead of release/renew.

**Symptom:** A route to the gateway exists and looks correct
(`ip route show default` names the right device), but `ping <gateway>`
replies "Destination Host Unreachable" **from an unexpected source IP**
(an address belonging to a different, dead interface).
**Cause:** Two interfaces on the same subnet (e.g. a dead bridge `vmbr0`
still holding a stale `10.0.0.0/24` address, and a newly-live NIC on the
same `10.0.0.0/24`) create two competing "directly connected" routes for
that subnet. The kernel can pick the dead one for the connected-subnet
route even though the explicit *default* route correctly names the live
device - this is a distinct bug from the "wrong default route chosen"
class already fixed in `network.py`'s `_route_default()`.
**Fix:** `ip addr flush dev <the dead interface>` to remove its
competing subnet route entirely. Diagnostic tell: the ping failure's
reported *source* address, not the destination, names the culprit
interface.

## USB tethering

**Symptom:** An iPhone plugged in via USB enumerates in `lsusb`
(`05ac:xxxx`, Apple's vendor ID) but no network interface appears.
**Cause:** iPhones don't do RNDIS/CDC-ECM tethering like Android; they
need `usbmuxd` (daemon) + the `ipheth` kernel driver (in-tree, no extra
package needed) to expose a network interface at all.
**Fix:** `apt-get install -y usbmuxd` (pulls in `libimobiledevice` too),
unplug/replug the phone, accept "Trust This Computer?" on the phone if
prompted.

**Symptom:** Even with `usbmuxd` installed and the interface present
(e.g. `enxXXXXXXXXXXXX`), `dhclient -v` on it just repeats `DHCPDISCOVER`
forever with no `DHCPOFFER`.
**Cause:** The USB link-layer exists, but the phone's Personal Hotspot
isn't actually active/serving DHCP - "Trust This Computer" is not the
same as enabling tethering.
**Fix:** Explicitly toggle Personal Hotspot **on** on the phone (Settings
→ Personal Hotspot). If already on and still not working, toggle fully
off, unplug the cable, wait, replug, then toggle on again - activation
order matters more on Linux than on a Mac (where Apple's official driver
does more handshaking automatically).

**Symptom:** A working tether connection (real `DHCPACK` obtained) goes
dead a few minutes later with no action taken.
**Cause:** iPhone Personal Hotspot connections can go idle/inactive if
the phone's screen locks or after a period with no active data flow.
**Fix:** Keep the phone screen on/unlocked during testing; re-check
Personal Hotspot is still showing as active before re-testing.

## Wi-Fi

**Symptom:** Running `wpa_supplicant -i <iface> -c <conf>` in the
foreground (no `-B`) to watch its connection log, then pressing
`Ctrl+C` once connected, tears the Wi-Fi connection back down
(`CTRL-EVENT-TERMINATING`).
**Cause:** Without `-B`, `wpa_supplicant` *is* the foreground process;
killing it (Ctrl+C) kills the connection, not just a monitoring view of
it.
**Fix:** Use `-B` (background/daemonize) for the connection you actually
want to keep; only run foreground, disposable instances when you
specifically want to watch the association handshake once and then let
it be replaced by a proper backgrounded one.

## Hardware detection

**Symptom:** No wired network interface (`eth0`, `enpXsY`, etc.) appears
anywhere - not in `ip link`, not in `lspci -knn | grep -i ethernet`.
**Two real, distinct causes, not "broken drivers":**
1. **Disabled in BIOS/CMOS.** The onboard LAN controller can be switched
   off entirely, in which case it won't even enumerate as a PCI device
   until re-enabled in firmware setup.
2. **Dock-provided, dock unplugged.** Many modern thin laptops have no
   built-in wired port at all; Ethernet only exists via a USB-C dock
   (shows up in `lsusb` as e.g. `Realtek ... USB 10/100/1G/2.5G LAN`,
   chipset `0bda:8156`, driven by the in-tree `r8152` module - no extra
   firmware package needed).
**Fix:** `lspci -knn` (full listing, not grep-filtered, to catch even
unbound devices) and `lsusb` distinguish these from a genuine absence or
driver problem. A true hardware absence shows nothing in either listing.
