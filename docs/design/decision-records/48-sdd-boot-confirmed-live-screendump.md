# Decision record: `/dev/sdd`'s real Proxmox install confirmed live, via a real screendump

> **Drive letters in this record are as of when it was written and are not stable.**
> Identify drives by serial, never by `/dev/sdX`. As of 2026-09-30:
> serial `FD01N6557110C271B` (PC601, Proxmox install, `pve` VG) is `/dev/sdc`, and serial
> `MD89N41071210AP4E` (PC401, the Baseline drive) is `/dev/sdd`. Read the current mapping with
> `ls -l /dev/disk/by-id/ | grep -E 'FD01N6557110C271B|MD89N41071210AP4E'` (v0.2 rows 27-29).


Status: **confirmed, for real, with direct visual evidence** - the
first actual positive evidence this session has for any of Track A's
"verified on real hardware" claims, closing part of the gap decision
record 47 flagged as unconfirmed.

## What happened

Decision record 47 corrected the working plan's Track A1/A3 "STATUS:
complete, verified on real hardware" claims to "unconfirmed from this
session" - no decision record backed them, and this dev environment
has no `qm`/`pct`/`pvesh` reachable. The user then ran, themselves, at
the physical machine, the exact boot-only QEMU invocation this session
had proposed but been blocked from launching directly (harness safety
classifier - see the earlier conversation turn):

```
qemu-system-x86_64 -enable-kvm -cpu host -m 3072 -smp 2 \
  -drive file=/dev/sdd,format=raw,if=virtio,cache=none -boot order=c \
  -nic user,restrict=on,mac=52:54:00:aa:bb:01 \
  -smbios type=1,product=baseline-real-sdd \
  -serial file:/tmp/sdd-boot-serial.log \
  -display none -vnc :17 -monitor unix:/tmp/sdd-monitor.sock,server,nowait
```

This session then connected read-only to the already-running process's
QEMU monitor socket (`/tmp/sdd-monitor.sock`, PID `2449632`, confirmed
via `pgrep`) and issued `screendump /tmp/sdd-shot.ppm` - a real HMP
command over a real Unix socket, matching `drive_setup_install.py`'s
own established `send_monitor_command` pattern. The resulting 1280x800
image (converted to PNG for viewing) shows, unambiguously: the real
Proxmox VE web UI's login page - "PROXMOX Virtual Environment" header,
"Server View" / "Datacenter" tree, "Documentation"/"Create VM"/
"Create CT" buttons, and a real login form (User name / Password /
Realm: "Linux PAM standard authentication" / Language) - rendering
correctly inside the guest's own virtual display.

## What this actually confirms, precisely

- **Proxmox VE is genuinely installed and bootable on `/dev/sdd`** -
  the disk's `LVM2_member` signature (noted in decision record 47 as
  "consistent with *some* Proxmox-shaped install") is now confirmed
  to be a real, working Proxmox root, not just a leftover signature.
- **The Proxmox web UI is being served and is reachable from this
  guest's own display** - whatever is rendering this page (most
  plausibly Track A3's kiosk service - `cage` + `chromium` in kiosk
  mode, auto-started via systemd once firstboot's completion marker
  exists) is functioning, on real disk state, without this session
  having driven any of that setup itself this pass.

## What this does not confirm - still open, not overclaimed

- Not confirmed: that this is specifically `cage`+`chromium` (Track
  A3's exact mechanism) versus some other renderer - the screendump
  shows the rendered *result*, not the process tree producing it. No
  login was attempted (this session does not have and should not
  receive this system's real root credentials), so nothing internal
  to the guest (installed packages, firstboot's own completion state,
  network configuration) was inspected this pass.
- Not confirmed: A2's persistence backend, A4's VM operations, A5's
  sensor/VM dashboard data - none of those are visible from a login
  screen, and A2 specifically is still falsified by `/dev/sdb`'s
  current plain-ext4 state (decision record 46/47) regardless of what
  `sdd` shows.
- Not yet done: pushing this session's newer code (everything since
  whatever `provision.sh` run originally built this install - the
  harness session/write-grant work, the HarnessAdapter registry, the
  OpenCode adapter, `settings_web.py`'s wiring, and more) onto this
  real system. That needs either the existing root login (which this
  session doesn't have and won't request from the user directly - see
  the safety-rule discussion earlier in this session) or a decision to
  treat this as a fresh reinstall using `docs/INSTALL.md`'s corrected
  `--fetch-from http` procedure instead, which generates its own
  throwaway credential and needs nobody to hand one over.

## Verification performed

- Real `pgrep` confirmation the QEMU process is genuinely running
  against `file=/dev/sdd`, launched by the user, not this session.
- Real HMP `screendump` command sent over the real monitor socket;
  the resulting PPM/PNG is real captured framebuffer content, not
  synthesized or assumed.
- No login attempted, no credentials requested from or provided by the
  user, no data written to either drive during this verification.
