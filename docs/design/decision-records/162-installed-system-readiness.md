# DR162 — Installed-system readiness and missing network observations

Date: 2026-10-05

The acceptance checklist lacked one report covering actual storage, networking
and installed services. Added the authenticated `/installation-readiness` page,
linked in navigation and staged by provision.sh. It performs read-only checks:
existing storage_policy.verify_runtime verifies root/VG/PV and mounted role
identities, restrictions and capacity; network.check_lifeline observes address
and gateway; systemctl observes Baseline storage/persistence/firstboot/TUI/web
and Proxmox cluster/daemon/proxy units. Every required observation must pass.
Exceptions and unknown service states are visible blocked checks. The report
explicitly does not establish native cold boot or workload/data acceptance.

The firstboot facts_verification helper previously defaulted missing address
and gateway facts to True and accepted any truthy value. It now requires both
facts to contain the boolean True. Four failing tests were confirmed before
implementation. Existing firstboot state-machine tests continue to pass.

Validation: 66 focused unit tests passed, including storage policy, boot gates,
provision import staging, immutable inputs, review regressions and new direct
HTTP-handler authentication/rendering tests. Python threads and direct handlers
are synthetic evidence, not real sockets, physical hardware or Proxmox service
proof. Shell syntax and git whitespace checks passed. No live service restart,
credential operation or drive write occurred.

Queue74/75/78: combined readiness implementation and synthetic refusal evidence
are available. Real firstboot readiness, browser/VT acceptance, finished installer
Build/Rebuild execution and native cold boot remain open. DR158 remains historical;
INSTALL.md and the acceptance checklist are updated to describe current status.
