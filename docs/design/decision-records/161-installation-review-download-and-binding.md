# DR161 — Installation review: downloads and selected driver binding

Date: 2026-10-05

The reviewed source download ran in the single HTTP request handler. The unified
server now uses ThreadingHTTPServer; a stalled transfer cannot occupy the only
handler. Source transfers use a 30-second socket timeout and close on write
failure without trying to append a JSON error to an already-started download.
Request threads are daemon threads, as in the standard Python HTTP server.

Driver application now reads the device driver's sysfs module link through the
same host/guest runner. Success requires that observed owning module to match
the selected compatible module. Missing ownership and unchanged bindings to a
different module fail explicitly. No unbind/rebind operation is inferred or run.

Regression tests first reproduced three failures. The focused installation
suite passed 126 tests after the fixes, including actual Python thread dispatch
with synthetic handlers and fake-runner driver checks. These are unit evidence,
not live HTTP, physical driver switching, installed Proxmox or cold-boot proof.
The broader unit run finished with 3,078 passed, 235 failed and 59 errors:
292 permission denials and two serial-console timeouts. It ran before the final
additional concurrent-dispatch test. The log is
/tmp/baseline-installation-continuation-tests.txt; no full-suite success or
regression conclusion is claimed.

DR159 remains historical; this corrects its download implementation. Queue
72/74/76/78 and installer-acceptance-checklist.md remain open: remaining publisher
sources and package closure, real Build/Rebuild stage journaling, firstboot
readiness and physical acceptance. No physical drives or credentials changed.
