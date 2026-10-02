# DR127 — Initial portable recipe validation and stack locking

2026-10-02. Accepted; partial implementation of DR126/queue76.

## Implemented

New environment_recipes module and baseline-recipes CLI validate configuration-
only JSON recipes, export canonical JSON, calculate SHA256 identities, compose
an OS plus application recipes into a copied lock and verify embedded digests.
No workloads are installed, mutated or reported ready. Provision stages the
module and CLI. No AI runtime dependency.

Initial schema is intentionally narrow and enforced by Python allowlists:
Ubuntu desktop/server 24.04 amd64, Chromium on that platform, source SHA256,
three supported locale values and symbolic environment_console homepage only.
State declarations support OS /home and Chromium ~/.config/chromium, respectively.
These declarations are not exhaustive runtime coverage. Unknown fields, arbitrary
settings, private runtime fields, paths, source-local paths, unsupported IDs,
platforms, wrong kinds and duplicate applications refuse. Import rejects duplicate
JSON keys, malformed/deep documents and documents above 65,536 characters. Composition makes
no silent overrides and holds no references to mutable caller recipe dictionaries.
Stack runtime_applied is always false. No universal/interoperability claim.

Configuration-only export here accepts already-structured approved fields, not
an arbitrary runtime profile or disk. No password/hash, user documents, private
homepage URL, VMID or host path field exists. This is not a generic secret scanner.
Source digest pins a declared identity; no bytes are fetched, publisher trust
established, source locator resolved or installation confirmed. JSON Schema file,
repository/package locks, adapters, actual provenance and coverage remain open.

## Evidence

RED/GREEN cycles covered module absence, private/unknown field acceptance,
duplicate-stack acceptance, ambiguous JSON import and missing CLI. Final focused
suite: 11 passed in 0.15s, using actual parser and subprocess CLI, no native
Proxmox/storage fakes or hardware operations. Provision import staging and
whitespace checks passed. No credentials handled, VM started, data changed or
runtime sandbox tested. Evidence: verification/127.

## Remaining work and continuity

Queue76 remains partial: source/package acquisition locks, structured schema,
export preview/config capture, human web actions, dependency/override resolver,
more applications/media/platforms, full state coverage and build/instantiate/
retained rebuild adapters. Queue74 still requires selected mounted AppData,
profile migration, app identities/launch and two-app access proof. Rows59/60
full VM/off-drive restore and row75 incomplete recovery remain open.

DR126 remains history; its parser-not-built status is narrowed here. Current
INSTALL, queue, audit and handoff are updated; no historical evidence is rewritten.
This increment adds validation and composition, not template deployment or the
only-memory-loss rebuild guarantee.

Final guarded regression suite: **2,920 passed in 131.65s**. Implementation
commit5d1cc39. Unit/runtime claims remain separated as documented above.
