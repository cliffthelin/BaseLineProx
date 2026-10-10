# DR153 — iperf3 verification blockers and real hardware inventory

2026-10-04. Continues DR152 / REAL-003 and DR142 / REAL-006.

## Requested verification

The operator requested LAN throughput and installed-Proxmox workflow verification,
then continuation to the next task. Real host netlink observations identify
Ethernet `eno1` at 10.0.0.231/24 and Wi-Fi `wlp9s0` at 10.0.0.192/24.
These are two interfaces on the same host, not separate test endpoints. The
operator delegated endpoint discovery. Actual bounded one-second iperf3 client
attempts and unauthenticated Proxmox version queries checked 253 addresses:
the connected physical 10.0.0.0/24 excluding both host addresses, plus the
observed local virtual neighbor 10.255.33.43. None returned a successful iperf3
transfer or Proxmox version response on standard ports 5201/8006. This does not
establish that no such host exists on a different port or behind a firewall.
Evidence: verification/153/lan-discovery.json. No LAN throughput measurement
has been obtained; existing loopback measurements remain loopback evidence
only. No public/internet server or fabricated peer was substituted. No remote
configuration was changed. Local Multipass inventory was also attempted, but
its service requires operator authentication; no credential was requested,
accepted or used to proceed.

The established PC401 read-only diagnosis revalidated serial
`MD89N41071210AP4E`, measured size and PV/VG identity. Its root LV is still open
and referenced by 23 mount namespaces. The current diagnosis is preserved in
verification/153/pc401-mount-diagnosis.txt. Boot was not attempted against this
mounted target; no unmount, LVM deactivation, service restart, physical write or
host reboot was performed. Installed-Proxmox workflow verification remains
blocked under DR146/queue78. No disposable VM was substituted as physical proof.

Source inspection also identifies a REAL-003 workflow gap: SystemSectionApplier
sends a partial Diagnostics config, while config_pipeline requires firewall
to have been applied in the same request for server startup. An already active
firewall cannot satisfy that condition. No live installed web submission was
possible; this is a source finding, not a verified installed failure. The
dependency needs verified existing firewall readback or explicit safe apply
before live server startup, with actual runtime verification. No host firewall
was modified to obtain a passing result.

## Next independent task: REAL-006

The real inventory comparison failed before repair: `tailscale0` was absent
from collect_net although actual `ip -j link` reported it. The oneline parser
required whitespace/MAC after link type; `link/none` interfaces have no MAC.
The separator and MAC are now optional, preserving those interfaces without
inventing an address.

`tests/integration/verify_hardware_inventory_runtime.py` uses RealRunner and
actual ip/lsblk commands plus sysfs. The repaired inventory passed against all
five non-loopback interfaces, 45 PCI devices and their actual kernel-driver
bindings, and 13 whole-disk entries. No FakeRunner, mock output or synthetic
hardware was used. This is actual read-only development-host hardware evidence,
not installed-Proxmox deployment or physical cold-boot evidence. Evidence:
verification/153/hardware-runtime.json. Syntax and whitespace checks passed.

REAL-006's malformed/partial-output and unavailable-driver metadata handling
remain open; this record closes only the observed MAC-less interface omission.
INSTALL, SESSION_HANDOFF, v0.2 queue and runtime register reflect these limits.
DR146 and DR152 remain historical; neither is promoted to LAN or native-boot
verification. Changes remain local and the production web service was not reloaded.
