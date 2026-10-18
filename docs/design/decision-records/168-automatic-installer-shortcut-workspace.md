# DR168 — Automatic Installer continuation and grouped shortcut workspace

2026-10-07. Supersedes DR167's manual preparation/confirmation and no-resize
statements for the installed-drive update. Its evidence boundaries remain valid.

The operator explicitly requested automatic preparation and execution, selected
PC401 <PC401 drive serial>, and protected PC601 <PC601 drive serial>. The signed-in
browser can capture source inputs, review the exact serial, and request native
execution without repeated manual web forms. Session ownership, origin checks,
single-use expiry and native PolicyKit execution remain enforced. Native-pending
authorization is accepted only for this action by the actual PkexecRunner; it
cannot authorize another action or pass through a fake/general command runner.
No operator password is extracted, typed or stored by the agent.

The update helper can grow only disposable BASELINE to 50 GiB, retaining at least
16 GiB free in its verified single-device VG. It checks ext4 before extension
and records extension and filesystem growth separately. Retained roles are never
shrunk or formatted. Tests cover capacity refusal and native command guarding;
no actual growth or physical deployment has occurred at this checkpoint.

Installer uses the browser width with responsive phone-style icon groups over a
code-generated desktop landscape. Application and OS shortcuts show icon above
name, support drag-and-drop, and retain right-click configuration dialogs.
Reduced-motion settings are honored. Application registration persists native
package definitions; configuration is validated and saved as a draft, not
reported as installed. Multiple workload deployment, broader distro support,
complete definition loading in installed runtimes, and per-machine driver cache
and persistence remain open; this layout does not fabricate those capabilities.

Confirmed RED preceded the relevant unit implementations. Real Chromium exercised
actual HTTP, drag-and-drop, modal settings, draft persistence, full-width/mobile
layout and automatic jobs with synthetic drives and a synthetic privileged
executor. This is browser integration proof, not a real drive write or boot.
Playwright's drag check requires source and destination visible together; a
small initial viewport scrolled the destination out of view and failed the test.
The verified interaction uses a larger viewport, then checks narrow resizing.

Verification results are recorded under docs/verification/168. Queue72/74/75/76/78
remain open for general stages, distros/applications, capacity and physical boot,
network, firewall and persistence acceptance. DR167 remains historical. Current
INSTALL status is corrected below; no new physical verification is claimed.
