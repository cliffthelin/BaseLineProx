# DR155 — Standard-port throughput listener

2026-10-04. Extends DR152–154 / REAL-003 at the operator's explicit request.

The existing implementation already defaults both iperf3 roles to TCP 5201.
No production default change was necessary. Added an actual integration-test
mode --standard-port that omits explicit ports in server/client requests and
verifies the default listener and measured result. It passed with actual
SQLite, nftables, systemd and iperf3: 60723 Mbit/s virtual local traffic in an
isolated network namespace. No FakeRunner, physical LAN throughput claim or
new production implementation/TDD RED claim. Existing RED/GREEN is DR154.

Fresh discovery tested 253 connected private addresses; no working iperf3
standard-port peer or Proxmox version response was found. Read-only actual
host firewall inspection showed no baseline_lan table; replacing the desktop
firewall was not appropriate. An explicitly approved temporary operational
helper instead started a real listener bound to the observed physical Ethernet
address 10.0.0.231:5201. A unique port-specific nft table drops connections to
that address/port from outside 10.0.0.0/24; other host traffic is unaffected.
Readiness was observed by ss with the actual process PID 1559750. The helper
serves one client or waits at most 600 seconds, then terminates the process and
removes its temporary table in finally. Cleanup is programmed, not yet observed
at this record's creation. Abrupt helper termination can leave the temporary
table; it only restricts this diagnostic port. No permanent package/service
installation, existing firewall replacement, credential use or drive writes.

Another LAN device can run `iperf3 -c 10.0.0.231 -p 5201 -t 10` while the
listener is alive. No distinct client was available through the discovered
endpoints, so physical LAN throughput remains unverified. This temporary host
listener is distinct from the production web workflow, which was not reloaded.
Proxmox port 8006 is unrelated to iperf throughput and was not changed.
PC401/native boot remains open under DR146/queue78; REAL-003 optional LAN and
browser-active-test follow-ups remain open. Earlier records remain historical;
INSTALL, queue and handoff now describe the temporary endpoint accurately.
Evidence and helper snapshot: docs/verification/155.
