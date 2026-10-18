# DR302: PC401 serial-bound overlay boot observation

**Date:** 2026-10-11  
**Status:** virtual observation complete; physical acceptance open

## Context

DR301 corrected the PC401 serial guard and identity but recorded no new QEMU
boot. A follow-up used the exact PC401 disk serial in QEMU to avoid the
earlier guest storage-identity mismatch. Claude's latest peer review also
recommended an e1000e NIC to expose install-time NIC-name assumptions.

## Observation

QEMU/KVM attached PC401's raw disk as the backing source of a separate qcow2
copy-on-write overlay, setting its virtual block serial to
`MD89N41071210AP4E`. The NIC was e1000e. QEMU user networking used
`restrict=on` and forwarded only `127.0.0.1:18103` to guest port 8006. The
guest reached the BaselineOS console/dashboard and Proxmox HTTPS API. A request
to `/api2/json/version` returned `401 No ticket`; no credentials or login
attempt were used. `qemu-img check` passed after QEMU shutdown.

The guest display listed `ens4` but did not prove a configured bridge or IP.
Because QEMU networking was restricted, internet access was intentionally
unavailable. The port-forwarded API response is not evidence of physical LAN,
internet, firewall configuration, GUI login, or successful workload operation.
The bridge-port retry normalization raised in Claude's review is already
present in this checkout, including the list-of-lines case; its focused
`test_network_retry.py` suite passes 14 tests.

## Safety and remaining work

The overlay captured guest writes separately from the raw backing source, and
no base write was intended. However, host LVM inactivity was not established
before this attachment. Do not repeat raw-backed QEMU access until that state
is resolved via the approved application path. This record does not assert
native cold boot or that the physical drive is ready for acceptance.

Native boot, GUI/login, physical network/DHCP, internet, firewall, VM/container
workloads and persistent overlay behavior remain open under queue rows
72/74/75/76/78. DR302 supersedes only DR301's statement that no new QEMU was
started; DR301's guard and UUID conclusions remain current.
