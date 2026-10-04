# DR138: Authenticated installer plan editor and real read-only discovery

Date: 2026-10-03. Accepted incremental work for queue72/76.

## Decision and implementation

Add /install-plan and /install-plan/action under Baseline's existing session
and same-origin gate. GET renders the editor without reading drives. POST
supports only autofill, validate and compile; no execute/format/mount action.
All accepted actions use fresh discovery and the established install_plan
validator/compiler. The adapter refuses unknown boot identity before listing.
The UI allows JSON choice edits, reports every known validation error, previews
existing stage parameters and exports a validated plan. Changing choices clears
export; epoch checks discard stale responses. Invalid actions/extra fields and
plans over64KiB refuse before discovery; malformed field types refuse rather
than produce an HTTP500. No credentials/profile data are captured or exported.

provision.sh now copies the editor module. The compiler's obsolete statement
that a web editor does not exist is removed. It still explicitly says stages,
PARTUUID fstab application and physical deployment are unfinished.

## Verification and limits

TDD RED/GREEN covered autofill/edit/compile freshness, invalid commands,
changed partitions/missing volumes, authenticated actual loopback HTTP and
cross-site refusal, JavaScript parsing, size/type bounds, deployment staging,
updated unfinished-work disclosure and fail-closed boot identity.
The first browser probe used an incorrect cached executable filename and failed;
no success inferred. Corrected actual headless Chromium exercised autofill,
edit invalidation, stage preview, exported JSON roundtrip and stale-partition
refusal without page errors. Its listing was synthetic, not physical proof.

Separately, the native adapter actually read physical metadata in an isolated
checkout containing DR135 plus this increment. It found the known two SK hynix
drives and selected keep/retain. Validation refused because APPDATA_ADMIN and
APPDATA_PERSONAL are missing from the existing six-volume layout. No enrollment,
write, mount, partition change, credential rotation or provisioning occurred.
Raw discovery and private browser-session token remain untracked. Published
summary includes only the selected drives and partition IDs already scoped to
Baseline. The development UI screenshot uses synthetic identifiers.

Other safety review/dependency changes were already uncommitted or arriving
concurrently. They are preserved and excluded from this increment. Isolated
verification tests only its parent DR135 plus owned editor changes; it does not
claim DR137 safety fixes were published here. Full isolated suite:3099 tests passed in125.18s. Focused web/editor/auth/deployment
checks:115 passed in17.13s. Implementation commit04f4d88; reviewed evidence
is in verification/138/README.md. No updated ISO or end-to-end
provisioning/firstboot test was run in this increment.

## Open work / correction

Queue72/75/76 remain partial. Next: explicit mapping/migration for the physical
six-volume layout, PARTUUID mount application, a gated durable stage-runner and
web progress/reconciliation, locked app recipes joined to OS provisioning, then
fresh-install and firstboot proof in disposable targets before physical apply.
Drive enrollment UI, custom personas and other OS adapters remain open.
This read-only discovery supersedes the earlier current-document statement
that physical discovery could not run. DR135's failed sandbox attempt remains
historical evidence; no append-only record is edited. Current INSTALL/queue
receive the new status. Web editing alone is not readiness for main/deployment.
