# DR156 — Physical Ethernet/AP/Wi-Fi throughput on TCP 5201

2026-10-04 local (2026-10-05 UTC). Extends DR152–155 / REAL-003. Supersedes
the broad current-status claim that physical LAN throughput remains unmeasured.
The user requests resolving the lack of a working peer without FakeRunner.

## Method and scope

No discovered remote iperf3 peer or operator credential was required. Both
physical adapters were already connected to the same private /24. A temporary
macvlan endpoint on Ethernet eno1 was placed in its own network namespace,
with address 10.0.0.250 after three actual ARP duplicate-detection probes.
The server bound the physical Wi-Fi address 10.0.0.192 on standard TCP 5201.
Exact MAC neighbors and one host /32 return route forced data through Ethernet,
the physical LAN/access point and Wi-Fi instead of the host's local route.
Neither existing adapter was moved, disconnected or reconfigured. Temporary
port-specific nftables rules restricted the server to private LAN sources.

Actual loopback negative control transferred data but did not meet the physical
hardware-counter acceptance check. Forward and reverse five-second iperf3
transfers did meet it: transmitter TX and receiver RX hardware byte counters
must each grow by at least 80 percent of received payload, with >1 MB payload.
This is actual physical traffic, with virtual endpoint isolation; it is not a
virtual local transfer, separate-host workflow or wired-only link-capacity test.
No FakeRunner, mocked process, VM/QEMU or Proxmox target was involved. The earlier
temporary DR155 server initially occupied port 5201; this test refused to replace
it. Its confirmed owned process was stopped explicitly, triggering cleanup.

## Observed result

| Direction | Received TCP throughput | Received payload | Corroborating hardware counters |
|---|---:|---:|---|
| Ethernet to Wi-Fi | 189.359 Mbit/s | 119,406,592 bytes | eno1 TX +125,366,245; wlp9s0 RX +125,333,984 bytes |
| Wi-Fi to Ethernet | 138.174 Mbit/s | 86,376,448 bytes | wlp9s0 TX +91,258,196; eno1 RX +91,250,503 bytes |

These are short single-stream measurements of the current mixed wired/wireless
path, not guaranteed sustained throughput or a diagnosis of either adapter's
maximum capacity. Tests used actual staged iperf3 3.20 and iputils-arping; no
permanent package was installed. No production behavior was changed, so there
is no new production RED/GREEN claim. The runnable integration test preserves
the actual loopback rejection and occupied-port refusal contracts.

The test completed successfully. Independent read-only post-test observation
confirmed no owned namespace, child interface, /32 route, neighbor, temporary
firewall table or TCP 5201 listener remained. Both physical links stayed up.
This also resolves DR155's previously unobserved temporary cleanup. Existing
host firewall policy and default routes were not replaced; no drive, secret,
credential or production web process was changed.

Evidence: docs/verification/156/physical-lan-runtime.jsonl and cleanup.json;
reproducible test: tests/integration/verify_physical_lan_iperf3_runtime.py.
Syntax and diff whitespace checks pass. Existing decision records are preserved
as history; INSTALL, runtime register, v0.2 queue, checklist and handoff are
updated to describe this proof. REAL-003 separate-device/browser active traffic
and delayed-start/cleanup-failure checks remain open. Installed Proxmox/native
boot proof remains separate under DR146/queue78 and is not claimed here.
