# Resumption validation — 2026-10-07

Nine malformed/partial inventory regressions failed before production repair;
66 focused hardware and truthful-runtime-error tests passed afterward using
FakeRunner. `unit-tests.txt` records the unrestricted full unit suite:
**3425 passed in 163.82 seconds**, with no skips/deselections. Whitespace checks
passed. Unit-suite results remain separate from the read-only host observations.

`hardware-output.json` contains actual read-only RealRunner PCI/USB/network
observations: 45 PCI devices, 25 USB devices and five non-loopback network
interfaces. This checks compatibility with current command output; no independent
completeness comparison was performed. Block parsing is unit/fake-tested only.
Sandboxed USB probing refused with exit1; the approved unrestricted probe passed.

The sandboxed full suite encountered local socket EPERM; unrestricted validation
is required for its HTTP tests. An earlier unrestricted run lost its result when
the server restarted and is not counted as a pass. No drive write, operator
credential, installed-Proxmox or QEMU/native-boot verification occurred here.
