# Decision record 177: generated testing data destination

Date: 2026-10-09
Status: destination policy recorded; no data copied or generated.

## Decision

Per the user's instruction, future generated test output belongs under a new,
unique run folder at:

`/mnt/10TB/backup/baseline-backups/testing/<task>-<UTC timestamp>/`

This includes disposable VM images, test datasets, logs, and screenshots.
Test output must not go in `INSTALLER_CACHE` or under the CACHE checkout.
Each run gets a new folder; existing backup content is add-only and must not
be overwritten or automatically deleted. If the designated drive is absent
or read-only, stop before generating large or persistent outputs and report
the unavailable destination rather than silently choosing another location.

At the time of this decision, `/mnt/10TB` is mounted read-only as exFAT. No
test data was written. Verify that the mounted device is the intended backup
drive and is writable before a future test writes there. This does not change
the established storage-class separation or authorize changes to PC601.
