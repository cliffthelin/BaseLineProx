# DR131 — Locked VS Code source and fresh archive materialization

2026-10-02. Accepted; partial queue76, follows DR130.

Implemented strict baseline.vscode-build/v1 Linux-x64 envelope binding approved
five-setting configuration to publisher version, commit, URL and SHA256. CLI
lock/verify/fetch/install uses real HTTPS and real filesystem operations. URL/commit
identity and hash are checked; redirects and unknown envelope fields refuse.
Download is bounded512MiB; extraction bounded20,000 entries/2GiB with Python data
filter and expected archive prefix. Existing destinations and symlink ancestors
refuse. Unverified/partial files remain on failure; no automatic deletion/rollback.
New application, profile and empty extensions directory plus BUILD.json are created.
Provision stages module and executable CLI. No credential handling or AI dependency.

HTTPS publisher metadata and SHA256 are the trust mechanism, not detached signature
verification. Archive materialization is not a DEB installation or dependency resolver.
This app-specific envelope is not accepted by the general OS recipe stack yet.
Storage-class cache routing and runtime AppData ownership remain unimplemented.

TDD RED confirmed missing binding module, fetch, install and CLI before GREEN.
Five focused build tests passed; combined build/capture tests17 passed. Full unit
suite2,950 passed in127.53s; bash syntax and whitespace checks passed. Synthetic
tar/HTTP tests are not application runtime proof.
Actual publisher archive1.140.0 was downloaded and hash-checked, materialized into
a new directory, and launched with Xvfb and a separate profile. A temporary development
extension read all five actual workspace configuration values and quit. Runtime
version/commit matches publisher lock; evidence verification/131. No account login
or original operator profile read, managed guest/physical deployment, retained mount,
OS rebuild or isolation proof. Local telemetry/update exclusions used only for proof.

Open: durable managed guest reconciliation, generic stack binding, native dependencies,
source/extension locks on other platforms, richer capture, persistent AppData and
isolated launch74, VM/app backup59/60, recovery75 and replacement restore77. Spotify
adapter remains unimplemented. Current status/queue/remaining-work corrected to
reflect this increment; prior decision records remain historical, not false evidence.
