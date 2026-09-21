# Decision record: Answer-file and credential behavior

Date: pending
Investigator: Claude Code
Status: not started

**Carried forward from Investigation 1**: `prepare-iso --fetch-from http` is an officially documented mode where the booted installer fetches the answer file via an HTTPS POST at boot time (optionally pinned via `--cert-fingerprint`), rather than embedding it in the ISO. This should be evaluated as the primary secret-delivery design before falling back to `--fetch-from iso`. `root-password-hashed` is confirmed real and accepted by `validate-answer`. See [01-assistant-iso-feasibility.md](01-assistant-iso-feasibility.md).

## Evidence collected
(pending)

## Result
(pending)

## Remaining uncertainty
(pending)

## Accepted / rejected approach
(pending)

## Security implications
(pending)

## Tests added
(pending)

## Next milestone unblocked?
Not yet evaluated.
