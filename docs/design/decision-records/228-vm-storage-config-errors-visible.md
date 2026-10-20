# DR228: Invalid VM storage configuration stays visible

**Status:** Accepted  
**Date:** 2026-10-09

## Context

`vm_page._load_path` and `container_page.load_data` converted read or JSON
errors into default VM/container stores. A malformed, unreadable, or non-object
configuration could therefore make Baseline list or create workloads in a
different location than the operator had configured. Invalid configured paths
also silently selected the default. VM and container storage saves additionally
replaced unreadable existing configuration with a new one-key document.

## Decision

Only a genuinely missing configuration file or a missing key uses the
first-run default. Read failures, malformed JSON, non-object documents, and
invalid configured values raise `VmError`. VM and container storage loaders
apply the same path checks as their save forms, including rejecting system
directories, traversal, symlinks resolving into forbidden locations, and
INSTALLER_CACHE. VM and container storage saves refuse to overwrite unreadable
configuration. The VM and container pages and JSON status/action routes surface
storage-configuration failures rather than silently selecting another store.

## Evidence and scope

Eight integration checks passed, including real Linux paths (`/proc/self/mounts`
as malformed JSON and `/etc` as a directory where a file was expected) and
the production VM-host resolver. Path rules were checked against system,
installer-cache, traversal, and user-volume paths. No FakeRunner, FakeProc, or
generated fixture was used. Python AST parsing and `git diff --check` passed.
No Proxmox command, VM, or physical drive was accessed.

## Remaining work

This makes configuration observation truthful; it does not verify configured
storage availability or prove VM lifecycle behavior on native Proxmox. Those
remain open under v0.2 queue item 75 and v0.1 queue item 7.
