# DR152 — iperf3 owned listener readiness

2026-10-04. Extends DR142's REAL-003 repair; its submission-only behavior
remains historical. The operator required iperf3 focus and real verification
without FakeRunner. No new fake test remains in this increment.

## Behavior

Each server request creates a distinct transient systemd service with the
existing single-use iperf3 server and 600-second runtime limit. A request cannot
stop an earlier request's service when it encounters a port conflict. Success
requires active/running service state, a positive MainPID and a TCP listener
on the requested port owned by that PID. Five observations, each command
bounded to two seconds, allow short startup delays. No connection probe is
used: connecting would consume the single-use listener.

Unsuccessful observation stops only the new service, then reads its actual
state. Inactive/failed with PID zero, including an already collected unit,
confirms cleanup. Unknown cleanup remains an error with the unit name and
bounded remaining lifetime. Server start errors remain failures.

An optional `bind_address` selects a specific local/private/link-local address
(including loopback); unspecified/multicast/public values refuse. Omission
retains the existing server binding and LAN firewall dependency. No new UI
field or firewall rule is added. Invalid role values now refuse.

## Actual evidence

`tests/integration/verify_iperf3_runtime.py` executes RealRunner, actual systemd,
ss and iperf3 3.20 on the development Ubuntu host. No mocked process/socket
output or FakeRunner is used. Ubuntu packages were downloaded/extracted in
`/tmp/baseline-iperf-real`, not installed on the host; temporary copies of the
binary/library received a runtime search path to their extracted libraries.
The original downloaded packages remain unchanged. Administrative execution
was explicitly approved through the harness. The first real failing test
exposed ignored binding; the next exposed inaccurate collected-unit cleanup.
Both passed after repair.

Final actual checks passed: loopback binding, owned listener readiness,
competing service port conflict with verified cleanup, original listener
survival and successful one-second JSON transfer, automatic single-use exit,
installed-tool/no-peer feedback, missing executable refusal and invalid inputs.
The final loopback transfer measured 50308944046.899734 bits/s. This is a local
transfer, not a LAN/network performance measurement. Evidence: verification/152.

No physical drive writes, native boot, Proxmox deployment, LAN transfer,
browser submission, artificially delayed startup or cleanup-failure runtime
proof occurred. The wait/cleanup failure branches need additional real runtime
coverage. REAL-003's server mechanism is implemented with real host evidence;
full diagnostic workflow verification remains open. Other runtime tasks and
PC401 boot recovery remain unchanged.

INSTALL, runtime task register, v0.2 queue and SESSION_HANDOFF are updated.
DR142 is preserved as history; its earlier unverified submission statement
is superseded here for this code path, not for other operations.
