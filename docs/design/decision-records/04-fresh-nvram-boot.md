# Decision record: Firmware and boot portability

Date: 2026-09-20
Investigator: Claude Code
Status: complete (legacy-BIOS-only portion deferred per instruction — not needed unless the real target requires legacy boot)

## Scope actually run, per explicit instruction to keep this fast

No new frameworks, wrappers, or test matrices were built. This reused the exact pipeline already proven in Investigation 3 (`run_final.sh`, unmodified) to regenerate one image, then ran two QEMU boots by hand against it. The image (`target.img`, 16GB sparse / 7.1GB actual) is **preserved**, not deleted, pending review — at `experiments/m0-inv3/runs/m0inv3-final-Pww7AS/target.img` (gitignored, not committed).

## Step 1–2: install + reboot-to-disk, same QEMU session

```
qemu-system-x86_64 \
  -enable-kvm -cpu host -m 3072 -smp 2 \
  -drive file=<workspace>/target.img,format=raw,if=virtio,cache=none \
  -cdrom <workspace>/prepared.iso \
  -boot order=c,once=d \
  -netdev user,id=net0,restrict=on,guestfwd=tcp:10.0.2.100:8443-tcp:127.0.0.1:<port> \
  -device virtio-net-pci,netdev=net0,mac=52:54:00:ba:5e:11 \
  -smbios type=1,product=baseline-m0-final-run \
  -vnc :40 -monitor unix:<workspace>/monitor.sock,server,nowait -serial file:<workspace>/serial.log
```

- **t=100s**: installer's own explicit success sequence captured (`boot1_10.png`) — `100.0% - installation finished`, `Finished: 'ok'`, `Installation done, rebooting...`. Same signature as Investigation 3's confirmed-success rerun.
- **t=110s**: `once=d` worked as intended — the reboot booted from the hard disk, not the CD (`boot1_11.png`): `Found volume group "pve" using metadata type lvm2`, `/dev/mapper/pve-root: clean`, `Booting from Hard Disk...`, `GRUB loading..`, `Welcome to GRUB!`.
- **t=120s**: reached the real Proxmox login prompt (`boot1_12.png`, sent to the user): `Welcome to the Proxmox Virtual Environment. Please use your web browser to configure this server - connect to: https://[fec0::5054:ff:feba:5e11]:8006/` followed by `m0inv3-final login:`.

QEMU was then stopped with a clean HMP `quit` via the monitor socket.

## Step 4–5: fresh OVMF NVRAM, no installer ISO, no host block devices

```
qemu-system-x86_64 \
  -enable-kvm -cpu host -m 3072 -smp 2 \
  -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd \
  -drive if=pflash,format=raw,file=<workspace>/OVMF_VARS_fresh.fd \
  -drive file=<workspace>/target.img,format=raw,if=virtio,cache=none \
  -netdev user,id=net0,restrict=on \
  -device virtio-net-pci,netdev=net0,mac=52:54:00:ba:5e:11 \
  -vnc :50 -monitor unix:<workspace>/monitor_uefi.sock,server,nowait -serial file:<workspace>/serial_uefi.log
```

- `OVMF_CODE_4M.fd` (read-only firmware) and a **fresh copy** of `OVMF_VARS_4M.fd` (the template, unmodified, copied into the workspace immediately before this boot — no NVRAM state from the install carried over) from the `ovmf` package already installed on this host (`/usr/share/OVMF/`).
- **No `-cdrom`, no `--fetch-from` answer server, no installer content of any kind** — only the two pflash firmware files and the installed disk.
- **No host block device**: all three `-drive`/pflash paths are either the read-only system-package firmware file or workspace-local files; no `/dev/*` string appears in the command.

**Result: `boot_success`.** At **t=10s** (`uefi_1.png`, sent to the user) the guest had already reached the identical real Proxmox login screen — `Welcome to the Proxmox Virtual Environment... https://[fec0::5054:ff:feba:5e11]:8006/`, `m0inv3-final login:`. Boot-to-login under completely fresh, blank UEFI NVRAM took well under the first 10-second sampling interval.

QEMU was stopped with a clean HMP `quit`.

## Reported results

- **Boot succeeded or failed**: succeeded, both times (BIOS-mode reboot-to-disk, and fresh-NVRAM UEFI boot).
- **Time to login screen**: BIOS-mode reboot-to-disk reached login by t=120s of the *combined* install+reboot session (install itself accounts for ~100s of that; the disk-boot-to-login portion was under 20s). Fresh-UEFI-NVRAM boot reached login in **under 10 seconds** — the first sampling interval.
- **Whether fresh NVRAM was sufficient**: **yes**. The installer itself ran under legacy BIOS (`-boot d`, no OVMF at all, per Investigation 3) — this is the exact case Investigation 4 exists to check, since Proxmox's installer must have written a genuinely portable EFI bootloader into the ESP for this to work. It did: a completely blank NVRAM store, never touched by the installer, booted straight to a working login prompt with no manual EFI boot-manager intervention required.
- **Shutdown result**: not performed this round — the current instruction's step list ends at "capture the login screen or the exact boot failure; report the result and stop," and explicitly said not to expand scope. Both QEMU instances were stopped via a clean monitor `quit` (not `kill -9`), which is a clean stop of the *process*, not a normal in-guest shutdown of Proxmox itself (no login/shutdown command was issued inside the guest). If a verified normal-shutdown result is needed, that's a small, separate follow-up, not performed here per the "keep it fast" instruction.
- **Any visible errors**: none in either boot. The only anomaly in the whole sequence is the repeated-CD-boot behavior from the first (pre-`once=d`) attempt in Investigation 3 — see below, not observed this run since `once=d` fixed it.

## Harness defect, not a curiosity — recorded as required

The earlier behavior (Investigation 3, before `once=d` was used) where a successful install's own reboot re-entered the same automated installer because the virtual CD-ROM couldn't be ejected and `-boot d` still preferred it, is recorded here as a **defect in the boot-order handling of this project's QEMU harness**, not a harmless artifact:

**Risk**: in a real unattended workflow — including, eventually, Milestone 3's physical-drive path — leaving installation media first in the boot order after a successful install means an unexpected/unplanned reboot (crash, power event, operator error) could cause the *same* automated installer to run again against an already-installed, now-data-bearing disk. Given the installer's answer file directly controls disk selection (Investigation 2's finding), a second unattended pass is a real destructive-reinstall risk, not merely a cosmetic loop.

**Fix confirmed working in this investigation**: `-boot order=c,once=d` — boot the installer media exactly once, then prefer the installed disk (`c`) on every subsequent boot, including the installer's own post-install reboot. Verified directly: the same pipeline that looped back into the installer under plain `-boot d` went straight to the installed disk under `order=c,once=d`.

**Requirement carried forward**: `once=d` (installer-once) followed by disk-first default boot order is **mandatory** for every future QEMU invocation in this project that boots an installer ISO — plain `-boot d` (or any config that leaves the installer media first-priority indefinitely) is disallowed. This should be encoded as a hard requirement in Milestone 1's real implementation of the install pipeline, not left as a convention.

## What this does and doesn't establish

Confirmed: the specific image produced by this project's automated-install pipeline boots correctly under both legacy-BIOS disk-boot and fresh-UEFI-NVRAM conditions, reaching a real, working Proxmox login prompt each time, with no host block device or installer media involved in the fresh-NVRAM case.

Not run, per explicit instruction ("do not run the legacy BIOS test yet unless the intended physical target actually requires legacy boot"): a from-scratch legacy-BIOS-only boot test (distinct from the BIOS-mode *reboot* that happened incidentally as part of step 1–2, which was legacy BIOS by default since no OVMF was specified there either — so legacy BIOS boot-to-login was, in fact, also demonstrated as a side effect of steps 1–2, just not as its own isolated, deliberately-scoped test).

Not tested: a verified clean in-guest shutdown; whether the fresh-NVRAM boot remains stable across a second/third boot cycle; any hardware-specific UEFI quirks a real physical machine's firmware might introduce that OVMF's implementation doesn't reproduce.

## Whether Investigation 5 is unblocked

Yes for boot-portability purposes — the image is confirmed to boot correctly under fresh UEFI NVRAM. Investigation 5 (offline staging containment) does not depend on this result and was never blocked by it in the first place.
