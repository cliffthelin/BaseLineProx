# ADR 0001: Bare-metal network bootstrap gotchas

Status: accepted, informed by the V0.1 bare-metal test.

## Context

Proxmox VE's installer asks for network settings (IP/gateway/DNS/FQDN) and
writes them as a **static** `/etc/network/interfaces` config, not DHCP. When
a Baseline image is built and tested under QEMU first (as V0.1 was), those
install-time values are whatever the virtual test network used - and they
get baked permanently into the disk image. Moving that same disk to real
hardware does not re-run the installer or re-negotiate anything; it boots
straight into the stale static config.

Two concrete symptoms hit during the V0.1 bare-metal test:

1. `bridge-ports` in `/etc/network/interfaces` referenced `nic0` - the
   virtio device name QEMU happened to assign. That device name doesn't
   exist on real hardware, so the bridge wasn't attached to anything.
2. `address`/`gateway` were the QEMU SLIRP throwaway values
   (`10.0.2.15`/`10.0.2.2`). Baseline's own `network` diagnostic correctly
   reported `gateway_reachable: FAIL` - it wasn't wrong, the config really
   was unreachable - but the *cause* (a stale install-time artifact, not a
   real fault) required reading `/etc/network/interfaces` and recognizing
   the mismatch to actually fix.

A second, unrelated finding from the same session: a laptop's wired NIC can
be invisible to Linux for reasons that have nothing to do with drivers -
BIOS/CMOS may have the onboard LAN controller disabled entirely (no PCI
device enumerates at all until it's turned on), or wired Ethernet may only
be provided through a USB-C dock (a `Realtek ... USB 10/100/1G/2.5G LAN`
device, chipset `0bda:8156`, needing the in-kernel `r8152` driver - present
and working out of the box on a stock Debian kernel, no extra firmware
package needed).

## Decision

- **Provisioning should default to DHCP**, not static, whenever the target
  network isn't known in advance - which is every V0.1 install, since the
  whole point is a disposable image moved to arbitrary hardware. Don't
  reuse install-time-entered values as the runtime config.
- **`network`'s diagnostic output is trustworthy as reported** - the fault
  it named (`gateway_reachable: FAIL`) was real and precise. What's missing
  is a *second-order* check: is this specific failure explainable by a
  known artifact class (stale static config, wrong bridge-port device
  name) rather than a genuine hardware/link fault? That's a candidate for
  a future `baseline diagnose network` command, not solved yet in V0.1.
- **Hardware detection notes for the operator/AI-assist layer**: "no wired
  NIC visible" can mean disabled-in-BIOS, dock-provided-and-unplugged, or
  genuinely absent - `lspci -knn` (all PCI devices, not just bound ones)
  and `lsusb` (dock/USB adapters) distinguish these; a real absence shows
  nothing in either listing.

## Consequence

Before/during provisioning on real target hardware, reset `/etc/network/
interfaces` to DHCP against the actual physical NIC name present on that
machine, rather than trusting whatever the install-time config says.
`boot/provision.sh` should gain this as an explicit step (not yet done -
tracked as follow-up, since V0.1's provisioning script predates this
finding).
