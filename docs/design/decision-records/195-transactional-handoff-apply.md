# DR195: Handoff packet application rolls back partial writes

Date: 2026-10-09  
Status: accepted

## Context

The first-run wizard applied handoff directories with `copytree` and then copied
SSH keys. If a later copy failed, earlier files had already overwritten machine
state and newly introduced files remained. DR193 made cleanup errors visible
and DR194 made hostname changes reversible, but multi-file packet application
was still partial on failure.

## Decision

Resolve the packet's regular-file copy set and target directories before making
changes. Reject source links, unsafe destination path components, non-regular
destinations, duplicate target paths, and SSH host-key names outside the
collector's six-file allowlist. Back up only existing files the packet will
overwrite and the metadata of destination directories whose mode or timestamps
will change; do not clone whole Baseline data trees. Apply the file and
directory metadata changes, and on failure restore the prior files, restore
directory metadata, and remove newly created files/directories. Report all
rollback errors with their paths. Keep authorized_keys intentionally excluded
from automatic restore.

## Evidence

A regression injects failure at the root SSH-key copy after Baseline config
files were already applied. It verifies previous file content is restored, new
files are removed, and existing SSH state remains intact. A successful-merge
regression verifies packet files are applied while unrelated files survive
and private-key mode is 0600. Another regression refuses an unrecognized SSH
configuration file before applying any packet files. Six setup-wizard tests,
29 real-GPG handoff tests, and 36 direct-VM tests passed (71 total). Wizard destinations and failure
injection are synthetic; the handoff packet tests use a throwaway GPG home. No
real packet, credential, hostname, host, or drive was modified.

## Remaining work

Rollback itself can fail under filesystem or permission errors; the wizard now
reports each affected path, and its outer cleanup still removes decrypted
staging. No live-host restore was attempted. Existing records DR193 and DR194
remain historical and are superseded only for the cleanup and hostname details
they describe.
