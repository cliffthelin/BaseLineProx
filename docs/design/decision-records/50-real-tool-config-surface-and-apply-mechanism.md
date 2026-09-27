# Decision record: real per-tool config surface researched; apply-at-boot mechanism built for the two richest ones

Status: **implemented, unit-tested (14 new tests, 788/788 suite
passing). Not run against real hardware** - same standing constraint
as every other provisioning module this session.

## What was asked

Told directly that the configurator artifact (published this session)
needs to be more than a review UI: *"when this list is applied it
should be applying all of these configurations at boot... so when a
setting is made... that needs to come back here to this form and be
determined how to config automatics once installed... walk through
each of the 5 applications and general Proxmox. This is one
configuration file to rule them all."*

## What was actually researched, not guessed

Local man pages on this machine (`man smartd.conf`, `man ethtool`)
were read directly this session:

- **`smartmontools`** (`smartd.conf(5)`): real per-device directives -
  `-H` (health check), `-a` (monitor all, shorthand for several
  defaults), `-o VALUE` (automatic offline testing on/off), `-S VALUE`
  (attribute autosave on/off), `-s REGEXP` (scheduled self-test,
  `T/MM/DD/d/HH` format), `-m ADD` (warning email), `-M TYPE`
  (once/daily/test email frequency). All six are now real fields in
  the configurator's Proxmox Tools tab, not the placeholder
  device-selector-only version from the previous pass.
- **`ethtool`** (`ethtool(8)`): real per-interface tuning - `-s/--change`
  (autoneg, speed, duplex, wake-on-lan), `-K/--offload` (rx/tx
  checksum, tso, gro - four of the many features `ethtool(8)` defines,
  deliberately the ones this project's own diagnostics scope cares
  about), `-A/--pause` (pause-frame autonegotiation). Also now real
  fields, not just an interface selector.
- **`lm-sensors`/`nvme-cli`**: checked and confirmed genuinely passive.
  `sensors.conf(5)`'s own config surface (chip/label/ignore/compute
  statements) relabels *already-detected* readings - it isn't a
  run-time choice, and `sensors-detect` handles chip discovery itself,
  non-interactively. `nvme-cli`'s configurable subcommands
  (`set-feature`, `format`, `sanitize`) are destructive maintenance
  operations, out of scope for a diagnostics tool. Neither was given
  new fields - this is a confirmed, researched "no" for both, not an
  omission.
- **`iperf3`, Proxmox Core (`datacenter.cfg`)**: no local man page for
  `iperf3` on this machine; `datacenter.cfg`'s fields (keyboard,
  console viewer, email_from, http_proxy, migration bwlimit) are from
  general knowledge, not a local authoritative source checked this
  session. Both are explicitly marked `coded: false` in the
  configurator and have **no apply function in this commit** - stated
  honestly rather than silently promised alongside the two that do.

## What was built

`baseline/lib/config_apply.py` - `build_smartd_conf` (pure generation:
a directive is only present when its configurator toggle/value implies
it - an unset email means no `-m`/`-M` at all), `apply_smartd_config`
(writes `/etc/smartd.conf` via `write_text_atomic`, then
`systemctl reload-or-restart smartd`), `ethtool_change_argv`/
`ethtool_offload_argv`/`ethtool_pause_argv` (pure `-s`/`-K`/`-A` argv
builders), `apply_ethtool_config` (runs all three in order, stops at
the first real failure - a later command is never attempted once an
earlier one fails). Uses the fuller `repair.Runner` interface (not the
minimal `run()`-only shape other provisioning modules use this
session) because writing `/etc/smartd.conf` needs `write_text_atomic`.

The configurator artifact itself (published earlier this session,
republished with these new fields) is the "one configuration file"
half - `baseline/lib/config_apply.py` is the "actually applies it"
half. They are not yet connected: nothing pulls the configurator's
saved `db` document into a call to `apply_smartd_config`/
`apply_ethtool_config` yet - that wiring (read `config/proxmox`,
call these two functions, likely from a new firstboot or
settings_web-adjacent step) is real, separate follow-up work.

## What this deliberately does not do

- Does not apply anything to `iperf3`'s extra fields or any Proxmox
  Core setting - no apply function exists for either, matching their
  `coded: false` status in the configurator honestly.
- Does not connect the configurator's saved config to these apply
  functions yet - the two pieces exist, wiring them together is next.
- Does not touch `lm-sensors`/`nvme-cli` - confirmed, not just assumed,
  that neither needs one.
- Not run against real hardware - `/etc/smartd.conf` has never
  actually been written by this code, `ethtool` has never actually
  been invoked by it.

## Verification performed

- RED confirmed first: `ModuleNotFoundError: No module named
  'config_apply'` before any implementation existed.
- 14 new unit tests: `smartd.conf` generation (directives present only
  when implied, email directives entirely absent when blank - not
  emitted as empty flags), all three `ethtool` argv shapes (including
  autoneg-off correctly adding speed/duplex, autoneg-on correctly
  omitting them), and the Runner-executed operations (`smartd.conf`
  written + reload attempted; `ethtool`'s three commands run in order
  and stop at the first real failure).
- Full suite: 788/788 passing (774 before this change), no
  regressions.
- `config_apply.py` byte-compiles clean.
