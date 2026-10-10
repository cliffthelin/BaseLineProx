# DR150 — Durable installer and recipe drafts

Accepted 2026-10-04, direct operator request to resolve the missing persisted
source in DR149. Supersedes only DR149's draft-source limitation.

The production web server owns a SQLite draft store in its configured persistent
state directory (`configuration-drafts.sqlite`). Each authenticated username has
one current installer draft and one current recipe draft. The recipe record
includes its optional application recipe. Saving accepts incomplete configuration
so unfinished choices can survive an application restart. It never executes,
validates against hardware, verifies a publisher, or marks a plan applied.

Both editor pages load their saved record before enabling editing and autosave
changes through authenticated same-origin routes. Templates, imported recipes,
discovery/autofill and AppData mappings use that same draft lifecycle. Reopening
restores the typed controls. Loading/saving failures remain visible and can be
retried. Unsaved changes trigger the browser's normal navigation warning.

Transactions compare the editor's expected revision before writing, so an older
tab cannot overwrite a newer draft. On conflict, the page preserves local choices
and offers an explicitly labelled reload/discard action. Records are owner-scoped;
clients cannot supply another username. Existing role restrictions remain in force.
Draft payloads are finite JSON objects limited to 64 KiB and 32 nesting levels;
credential fields are refused. The database file is mode0600. Recipe envelopes
must contain the recipe object and optional application recipe object.

Master Config reads those same saved records for the logged-in user and displays
revision, update time, configuration and the explicit saved-draft/not-applied
status. No saved record is a legitimate empty state; an unavailable/corrupt store
is an error. Browser-local unsaved keystrokes are not represented as saved state.

Verification: real SQLite temporary-file reopen, isolation, transaction conflict,
invalid-payload rejection, unchanged prior revisions and file mode tests; real
local HTTP tests cover both draft routes, Master Config aggregation, ownership and
role rejection. Real Chromium exercises installer and recipe autosave/reload and
two-editor conflict recovery using the production renderers and a real isolated
SQLite store. Host/apply configuration in that browser fixture is test data. No
physical target write, native drive boot or recipe installation was performed.
This proves persistence across application restarts, not preservation across an
OS rebuild whose persistent state routing remains a separate physical requirement.

Remaining configuration/installer work is in configuration-web-checklist.md;
this draft-persistence item under queue72/75/76 is resolved. DR149 remains history.

Deployment: the desktop Baseline web application was reloaded with the new
modules, retaining its configured state directory. GET /login returned HTTP200.
Operator sessions reset on reload; log in again to use the updated pages.
