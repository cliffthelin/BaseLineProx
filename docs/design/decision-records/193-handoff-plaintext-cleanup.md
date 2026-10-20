# DR193: Handoff restore never hides decrypted-staging cleanup failure

Date: 2026-10-09  
Status: accepted

## Context

`baseline-setup-wizard` decrypts a handoff packet into
`/root/.baseline-handoff-restore`. It called `shutil.rmtree(...,
ignore_errors=True)` after declining or applying the packet. If removal failed,
the wizard silently continued and could report setup complete with decrypted
credentials still in the staging directory. An apply failure also left cleanup
to an abrupt exit without a controlled status.

## Decision

Use strict staging removal and verify the directory is gone. A declined restore
stops with an error if cleanup fails. An apply failure attempts cleanup and
reports both errors if that also fails. If apply succeeds but staging cleanup
fails, report that files were applied while plaintext staging may remain and
stop the wizard with a nonzero result; never print the success message.

## Evidence

A regression test injects a cleanup failure that respects the old
`ignore_errors=True` behavior. Before the fix, the wizard returned success
without raising; afterward, the failure is visible. The focused wizard test and
all direct VM-host lifecycle tests passed (37 total) using synthetic filesystem
and command behavior. No encrypted packet, credential, or physical host was
used.

## Remaining work

The wizard still applies selected files directly and does not offer transactional
rollback for a partial restore. That separate behavior remains governed by
handoff/restore design work; this decision only prevents false cleanup success.
