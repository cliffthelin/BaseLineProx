# DR194: Setup wizard reports and rolls back incomplete hostname changes

Date: 2026-10-09  
Status: accepted

## Context

`baseline-setup-wizard.apply_form()` wrote `/etc/hostname` and ignored
`socket.sethostname()` errors. The wizard could therefore show setup complete
while the live system kept its old hostname. Reversing the order alone could
leave the live hostname changed when the persistent write failed.

## Decision

Read the current persistent and live hostnames first. Apply the live value and
then persist it. If the live change fails, leave the file untouched and stop.
If persistence fails, attempt to restore the old file and live hostname and
include any rollback failures in the surfaced error. The wizard exits with a
failure result rather than continuing to its setup-complete message.

## Evidence

Two regressions cover a denied live change and a failed persistent write. The
first leaves the persistent hostname unchanged; the second confirms the live
hostname is restored. The focused setup-wizard, handoff, and direct VM-host
tests passed, 68 total, with synthetic filesystem and socket behavior. No real
hostname, credential, host, or drive was changed.

## Remaining work

The wizard's multi-file handoff application is still not transactional. DR193
only fixes plaintext staging cleanup and reports those failures; a failure
while copying a packet can still leave earlier destinations applied.
