# DR128 — Human recipe validation, composition and export controls

2026-10-02. Accepted; narrows queue76 human-interface gap after DR127.

## Implemented

New authenticated admin /recipes page and /recipes/action route reuse the strict
DR127 parser/export/lock implementation. Paste JSON or load a local file, validate
an individual recipe, compose OS plus optional app, or verify an imported stack.
Validated output is displayed and downloadable as JSON. No template inputs are
saved in server state, journals or workload jobs; it is a bounded read-only
transformation. No allocation, install, migration or overlay apply is performed.

Same-origin POST and existing session/role gates apply; operator/anonymous access
is refused. Unknown action/fields, malformed/ambiguous/private/unsupported recipe
input and changed digests refuse without returning an export. Responses state
runtime_applied=false and sources_verified=false. Source verification and complete
retention coverage are visibly distinct from configuration validation. UI uses
textContent for result/error display. Changing inputs invalidates the previous
export; asynchronous responses are checked against the input snapshot. Export
uses a fixed filename and local Blob URL, not an uploaded private path. Browser
file picker has a64KiB limit; backend DR127 input limit is65,536 characters.

Provision stages recipe_page with the existing recipe module. Existing VM/LXC
jobs, originals and data remain unchanged. No guest accounts or credentials added.
No second independent installer or AI runtime dependency is introduced.

## Evidence and limitations

Confirmed RED: new HTTP page returned404 before implementation. GREEN: actual
local server validate/export/compose/verify requests and refusal/auth tests pass.
14 focused tests including the real subprocess CLI passed in0.68s. Node syntax
check and provision/whitespace checks passed. HTTP tests use fixture sessions and
host dependencies; no native VM, live sandbox, browser automation or physical
hardware verification. Evidence: verification/128, with scope stated explicitly.

## Open work and continuity

Queue76 remains partial: source acquisition/publisher checks, package locks,
structured JSON Schema, broader settings/media/dependencies, capture preview,
actual fresh instantiate and retained rebuild. Queue74 still needs mounted
AppData identity/profile migration/guest reconciler/isolated launch/two-app proof.
Rows59/60 full VM/off-drive restore and75 incomplete recovery remain open.

DR126/127 are preserved as history. Current queue, INSTALL, handoff and audit
follow-ups reflect the new human entry point. No recipe-validation result is an
installation, lossless-rebuild or applied-isolation badge.

Final guarded regression suite: **2,923 passed in130.96s**. Implementation
commite3660b6. Native guest/hardware and browser automation remain unverified.
