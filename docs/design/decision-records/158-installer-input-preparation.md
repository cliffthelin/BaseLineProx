# DR158 — Installer input preparation and remaining acceptance work

Date: 2026-10-04. Status: accepted implementation boundary.

The seven requested installer outcomes remain incomplete. Existing owned drafts,
compiled plans and durable workload jobs are useful components, not a completed
physical installer. The consolidated checklist is installer-acceptance-checklist.md;
its open work belongs to queue rows 72/73/74/75/76/78.

The Installer Plan now offers Prepare installation inputs. It waits for autosave,
submits the saved owned revision to an authenticated same-origin durable job,
and reports missing dependencies before any installation. Repeated request IDs
return the same job. A private immutable snapshot captures current code, selected
plan, current settings and saved recipe; exact file-set SHA256 checks detect
changed, missing or additional files. Credentials are refused. Publisher files
stay external source references and are checked against explicit HTTPS/SHA256
locks; detached publisher signatures are not inferred from hashes. Current
source acquisition and target apt/NodeSource/npm closure remain unfinished, so
preparation reports not ready and never installs a drive.

Service restarts classify running jobs as interrupted. Source-only jobs inspect
actual bundle files without calling VM backends. A damaged source preparation
can be acknowledged and replaced with a new preparation; physical stages are
not replayed. Installation stage checkpointing/resumption remains open.

Two genuine fresh-install omissions were repaired: the ISO payload lacked the
tests/console_font_check.sh invoked by provision.sh, and installed web source
resolution chose /opt instead of /opt/baseline-src. Actual current repository
capture/verification succeeded for 762 files; this is filesystem evidence only.

TDD regressions were confirmed failing before fixes. Authenticated HTTP tests
use real temporary SQLite and file operations; injected configuration fixtures
are test-only. Chromium checked the preparation button, saved revision and
missing-input display against fixtures, not production installation. An initial
full unit run found 3348 passes and two failures: a stale handler-selection test
harness and missing Operations integrity-alert label. Both were corrected;
the final full unit suite passed all 3352 tests with no deselections, skips
or failures. Focused installer/HTTP/deployment checks passed 128 tests. Evidence
is in verification/158. Production reload PID1576009 serves login HTTP200
with same-origin Referrer-Policy. Authenticated production interaction was not
performed by the agent; no operator credential was handled.

No physical target was written, mounted, booted or reformatted in this record.
DR146's earlier physical disk-QEMU result and DR153's recorded mount blocker
remain history, not new proof. No native cold boot, workload portal, complete
persistence acceptance or final-installer proof is claimed. Earlier decision
records remain append-only; INSTALL.md and the current queue are updated.
