# DR154 — Optional explicit network diagnostics and endpoint requirements

2026-10-04. Supersedes DR153's broad endpoint-blocker framing; extends
DR152/REAL-003. The operator asks which endpoint requirements matter and
requires TDD fixes rather than treating discovery defaults as prerequisites.

## What matters

There is no requirement to have an iperf3 server on port 5201 or a Proxmox
web endpoint on port 8006 before normal Baseline use. Those were discovery
defaults, not readiness gates. A throughput measurement requires a real
client/server pair using the same chosen port. Physical LAN throughput also
requires traffic through the physical LAN; local transfers do not prove it.
This is an optional diagnostic, not a firstboot requirement.

Proxmox-specific actions and installed-drive behavior still need a real running
installed target to be verified. It can be reached locally/by the established
SSH/QEMU mechanisms; an additional LAN host or standard-port web response is
not required. PC401's mounted root remains a distinct, important installation
verification blocker under DR146/queue78. It is not retired by this decision.

## Changes

Diagnostics option saves now perform actual SQLite persistence only, explicitly
reporting that no network test ran. Firstboot/config apply skips active iperf3
unless `run_active_diagnostics=True` is deliberately requested. The Settings
page has a separate manual Run network test form, outside autosave. Both
standalone and unified web handlers expose authenticated, same-origin POST
`/diagnostics/iperf3/run`; stale-persona checks are retained. A client run with
no chosen peer refuses instead of advertising a completed measurement.

An explicit server request reads the actual nftables policy rather than
requiring a firewall apply in the same Diagnostics request. Structural JSON
readback accepts the owned default-drop input chain, its known loopback/state/
DHCP/neighbor-discovery rules, and private source allowlists. Missing, unknown,
public-source or extra permissive rules refuse. Custom private subnets are
supported; readback does not rewrite the firewall. A failed requested firewall
change still prevents starting the server.

The transient server joins its caller's network namespace. This keeps the
service's socket in the same context as firewall and socket observations,
including a private application/test namespace. The existing unique service,
single-use server, runtime bound and observed cleanup are retained.
Successful pipeline details now reach the Run result, including the verified
listener/unit or the actual client measurement, rather than a generic success.

## TDD and actual evidence

Confirmed RED then GREEN cases: saving server options incorrectly demanded a
firewall; firstboot executed optional diagnostics; the explicit Run action/form
and unauthenticated refusal were missing; permissive rules could pass the
initial readback check; a Diagnostics-only request rejected an already active
policy; service creation used the manager namespace instead of the observation
namespace; and successful client output lost its measured throughput.

Five focused tests pass using real SQLite, RealRunner and public handler/render
contracts. No FakeRunner or mocked subprocess output was used for this proof.
The real HTTP server verifies authentication, cross-site refusal, option saves
and typed manual-form/JSON refusal of missing peers. Its sessions are fresh
project-generated throwaways, not operator credentials; native login is not
claimed by that test.

Actual nftables tests in a private network namespace passed default/private
policy readback and refusal of unconditional acceptance, public sources and
missing policy. Actual systemd/iperf3 settings-backend tests passed server
readiness and client measurement using chosen port 33275. The reported
60165 Mbit/s is a virtual local transfer, not physical LAN throughput.
Actual host-loopback regression passed listener ownership, competing port
conflict/cleanup, single-use exit, missing executable and invalid input checks.
Evidence: `docs/verification/154/`; scripts: `verify_iperf3_settings_runtime.py`,
`verify_iperf3_http_runtime.py` and `verify_iperf3_runtime.py` under tests/integration.
Syntax/import and whitespace checks pass. The old fake-based suite is not
reported as runtime evidence and was not run in this increment.

No desktop firewall rewrite, permanent host package install, physical drive
write, Proxmox deployment, native boot or physical LAN measurement occurred.
Successful browser-submitted active traffic and delayed-start/cleanup-failure
runtime cases are not claimed. They remain optional diagnostic verification;
physical installer/firstboot/storage proof stays open under the existing queue.

INSTALL, runtime register, configuration checklist, v0.2 queue and handoff are
updated in place. DR153 is preserved as history, including its discovery results
and earlier source finding now fixed. Source changes remain local; the running
production web process has not been reloaded by this increment.
