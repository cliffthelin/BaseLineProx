# DR232 — Store the custom application catalog in persistent state

**Status:** Implemented in the web and CLI paths; physical persistence mount remains unverified  
**Date:** 2026-10-09

## Context

DR231 corrected custom package source validation and loaded the catalog in the
application CLI, but its writable catalog location was still the installer
source tree. That couples user-created applications to replaceable source files
and can lose them during a source refresh. It also puts mutable catalog data
inside the source payload copied into future installer bundles.

## Decision

The web server stores custom application definitions in its configured state
directory under `application-definitions/`. The real server sets this to
`state/application-definitions`; the configured `/var/lib/baseline` state path
is declared by `boot/provision.sh` for redirection to `USER_PERSISTENCE`. The
source tree remains read-only input for shipped definitions and icons.

Catalog files are written through a mode-0600 staged file, fsync, and
no-overwrite hard-link publication. The staging file is removed in a `finally`
path. `baseline-apps` and `baseline-tasker` resolve the same state directory
(`BASELINE_STATE_DIR`, the writable system state path, or the user's local
state path) and reload the saved definitions in each new process. This is a
separate catalog namespace; it is not written to INSTALLER_CACHE.

## Evidence and scope

Six focused application-bundle contract tests passed. They cover source and
state catalog loading, exact package URL/digest validation, mode-0600 atomic
publication, duplicate refusal, and custom application loading in fresh
`baseline-apps` and `baseline-tasker` processes. Two installer-page tests
passed: one renders a state-backed shortcut, and one posts through a real local
HTTP server/session to save a catalog entry and read its configuration back.
That route test used no command fakes. `baseline-tasker catalog` ran against the
current repository. No FakeRunner/FakeProc, network download, package
installation, guest, or physical drive was used. The tests use context-managed
temporary state directories and leave no temporary directory behind.

The physical `USER_PERSISTENCE` bind mount has not been verified, so disk-level
survival across rebuild is not proven by these tests.

## Remaining work

Installer Plan input preparation still does not acquire custom application
packages, and no custom application has been downloaded, installed, or launched
in a guest. Continue queue item 76; full application overlay persistence,
guest behavior, and physical deployment remain open under rows 72–76 and 78.
This record supersedes DR231's source-tree location for user-created catalog
entries; DR231 remains history for source validation and package identity.
