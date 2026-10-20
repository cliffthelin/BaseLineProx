# DR197 — Selective handoff config restore

Date: 2026-10-09

## Decision

The Installer handoff flow restores only explicitly selected sections of the
archived `/etc/baseline/install-config.json`. It validates the archive path
using the existing INSTALLER_CACHE backup rules, requires exactly one
`etc/baseline/install-config.json` member, and reads that fixed member with
`tar -xOzf`. It never invokes archive extraction and therefore cannot write
archive-controlled paths.

Supported categories are network, firewall, SSH settings, tether, Proxmox
smartd/ethtool settings, and the two implemented driver package toggles.
Unknown keys and categories without an implemented action fail visibly.
Selected settings are applied through `config_pipeline`, then merged into the
current install config. Handoff is the final firstboot stage so the import is
not immediately overwritten by the normal apply pass. Diagnostics, user files,
credentials, SSH keys, and machine identity are outside this category flow.

The Installer handoff configuration includes an archive path field. No
archive picker or live archive inventory is claimed by this field.

## Evidence and limits

The regression was first run RED against the previous refusal implementation.
After implementation, 96 focused tests passed across config apply, pipeline,
and truthful-runtime error handling, using FakeRunner only. The tests cover
selected-section merge, preservation of unselected SSH config, exact-member
read, refusal when that member is absent, and rejection of unsupported
categories. No physical archive, installed target, credential, or hardware
was used. Disposable installed-system validation of archive parsing, runtime
effects, and user-file/SSH isolation remains open under REAL-004 / queue59.
