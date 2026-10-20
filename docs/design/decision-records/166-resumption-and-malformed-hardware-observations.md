# DR166 — Resumption and malformed hardware observations

2026-10-07. Continues DR142/DR153 REAL-006; reconciles living docs with DR165.

The saved GUI acceptance handoff and verification/165 already record successful
current-source KVM host kiosk startup, nested Ubuntu GUI/browser configuration
and two OS rebuilds retaining user data. INSTALL and the installer checklist
still contained pending-GUI statements. Those living entries now reflect DR165;
historical decision records remain unchanged. No new virtual or physical GUI
acceptance is claimed, and native cold boot remains open under rows72/78.

Hardware collectors previously ignored unrecognized command lines. A malformed
bus could therefore appear empty, or partially parsed output could silently omit
devices. Collectors now raise InventoryError tagged REAL-006 on unrecognized
nonblank PCI/USB/network lines and invalid block key/value records. Block records
must contain the requested fields without duplicate keys and a name/size.
Empty serial/model/transport remains valid for devices lacking those attributes.
Confirmed empty command output and intentional loopback/root-hub/loop exclusions
remain valid. The aggregate retains successful buses and reports a failed bus
as unknown with its error, rather than presenting incomplete observations.

Nine new regression cases failed before implementation. After repair, 66 focused
hardware and truthful-runtime-error tests passed using fakes. The unrestricted
full unit suite passed **3425 tests** in 163.82 seconds, with no skips or
deselections; git diff --check passed. Read-only RealRunner observations accepted actual output
for 45 PCI devices, 25 USB devices and five network interfaces on the development
host, with no FakeRunner. Block inventory remains tested against fakes only.
This is command-output compatibility evidence, not independent enumeration
completeness, installed Proxmox or QEMU/native-boot verification. No credentials
were handled and no physical drive was written. Evidence: verification/166.

REAL-006 remains open for unavailable driver metadata, missing stdout, outer
collector/real_volume_state fallbacks and real block command-output compatibility.
The strict parser can now surface unsupported output instead of hiding devices;
any genuine supported output rejected by it needs a captured-shape regression.
The runtime register, queue and session handoff retain these obligations.
