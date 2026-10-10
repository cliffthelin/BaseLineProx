# DR222: Container backup inventory errors stay visible

**Status:** Accepted  
**Date:** 2026-10-09

## Context

The retained-container backup listing silently skipped backup-set symlinks and
manifest symlinks, and treated a non-directory root as an empty listing. That
could make an existing retained backup appear absent. Malformed manifest JSON
escaped as a raw decoder exception instead of the backup API's `VmError`.

## Decision

The listing returns an empty result only when the container-backup root does
not exist or a set has no manifest yet. Root inspection/enumeration failures,
redirected/non-directory set entries, redirected/non-regular manifests, and
unreadable or invalid manifests produce `VmError`. Manifest identity is
validated before inclusion. Restore uses the same manifest validation and
checks archive file type, size, and digest before extraction.

## Evidence and scope

The container-backup, guest-backup, distro-container, off-drive-backup, and
Operations suites passed 139 tests. The new regression first failed because a
redirected set disappeared from the listing; corrupt-manifest and incomplete
set cases now distinguish errors from an unpublished manifest. Tests used
disposable files and scripted runners. No physical backup destination or
Proxmox container was accessed.

## Remaining work

Real destination inventory, backup, and restore remain open under v0.2 queue
items 56 and 59/60. This change does not establish real-drive or live-Proxmox
behavior.
