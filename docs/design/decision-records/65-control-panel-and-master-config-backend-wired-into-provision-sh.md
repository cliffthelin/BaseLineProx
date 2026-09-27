# Decision record: the real Master Config control-plane backend was never deployed - fixed, control panel deliberately kept operator-invoked

Status: **implemented and tested (961/961 suite passing). Not run
against real hardware** - same standing constraint as every other
provisioning change this session.

## What was found

Continuing the same kind of audit that found decision record 63's
7-module gap, I checked whether decision record 64's pivotal
deliverable - the real Control Panel web app built to satisfy "THIS IS
A WEB APPLICATION... IT IS NOT A FORM" - was actually reachable on a
real deployed machine. It was not. Worse, the gap was bigger than just
the control panel itself: **none of the real Master Config backend
built this session had ever been added to `provision.sh`**, five CLI
tools and seven library modules:

- `baseline-diff` (`config_diff.py`, `drive_installer.py`)
- `baseline-update` (`update_pipeline.py`)
- `baseline-backup` (`backup_restore.py`)
- `baseline-config-crypto` (`config_crypto.py`)
- `baseline-control-panel` (`control_panel_web.py`, `physical_device_safety.py`)

`tools/check_provision_deploys_all_imports.py` (decision record 63)
did not - and structurally could not - catch this on its own: it
audits the transitive-import closure of bin scripts `provision.sh`
*already* copies. None of these five were in the copy list to begin
with, so there was nothing for the checker to walk. This is a real,
known boundary of that tool, not a bug in it - noted here rather than
papered over.

## A second, unrelated real defect found along the way: a decision-record numbering collision

While tracing this, `docs/design/decision-records/` turned out to have
**two different files both named `57-*`** - this session's
`57-real-control-panel-web-app-not-a-static-form.md` and a separate
session's `57-vm-scripts-pinned-community-helper-scripts.md`, the
latter with a contiguous `57-61` sequence and five real
cross-references elsewhere in the repo (records 58/59,
`vm_scripts.py`'s docstring, the work-queue doc, the changelog).
Renumbering the unreferenced control-panel record to **64** (the next
free number, one file, zero cross-references to fix) was the correct
side to move; renumbering the other side would have meant editing five
files across two different sessions' work for no real benefit.

## The fix

All seven lib modules and four of the five CLI tools
(`baseline-diff`/`-update`/`-backup`/`-config-crypto`) are now staged,
chmod'd, and verified by `provision.sh`, identically to every other
real CLI tool in this project - copied, checked present-and-executable
before any activation step, same fail-closed discipline as everything
else here.

`baseline-control-panel` is also now staged, chmod'd, and verified -
but **deliberately not wired to any systemd unit**, unlike
`baseline-settings-web` (which got the full service treatment in
decision record 63's neighborhood). The reason is a real, checked
fact, not caution for its own sake: `control_panel_web.py` has **no
authentication of any kind** - anyone who can reach its bound
host:port can trigger backup, restore, selective update, and even
`/api/backup/encrypt` / `/api/backup/decrypt` (which take the password
as a plain JSON body field). Its CLI default (`--host 127.0.0.1`)
keeps it loopback-only, which is a real mitigation, but a bind address
is not authentication - `systemctl enable`-ing it as an always-on
service would mean every real deployed machine silently carries a
live, reachable door to those actions the moment anyone finds a way to
reach that port (a port-forward, a misconfigured proxy, a future
change to the default). It stays exactly what `vm_scripts.py` and
`quadlet.py` already are in this repo (their own decision records
57/58, in the *other* numbering sequence): operator-invoked-only,
started by hand when actually needed, until it has real session auth.

## What this does not do

- Does not add authentication to `control_panel_web.py` - that is real,
  separate work, not a deployment-staging fix. Flagging it here so it
  is not lost, not solving it in this pass.
- Does not extend `check_provision_deploys_all_imports.py` to detect
  "a real CLI tool exists in the repo but was never added to
  `provision.sh` at all" - that is a fundamentally different, fuzzier
  check (it would need to know which of this repo's many scripts are
  meant to be deployed vs. dev-only, which the import graph alone
  cannot tell it). Found this specific gap by manual, deliberate audit
  instead; a future pass could define that list explicitly if this
  bug class recurs a third time.
- Not run against real hardware - matching every other provisioning
  module this session.

## Verification performed

- `bash -n boot/provision.sh` - syntax clean after every edit.
- `tools/check_provision_deploys_all_imports.py` - zero gaps, run
  directly against this repo after the fix.
- Full suite: 961/961 passing, no regressions.
- Manually traced (`grep`) that no other file references decision
  record 57 by number under the control-panel meaning before renaming
  it - only the vm-scripts sequence's own real cross-references exist,
  confirming the rename side was correct.
