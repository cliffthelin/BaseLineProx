# 06 · USER_<PERSONA>

**Status: MVP completed** · [index](README.md)

One volume per persona, holding that person's own settings and state. Default
personas are `admin` and `personal` (`DEFAULT_PERSONAS`); any other is
opt-in. 50-200 GB each, `defaults,nosuid,nodev`. Not `noexec`: the scripts
inbox lives here and an operator may run a pushed script.

Renamed from `USER_PERSISTENCE_<PERSONA>` because that name ran past the
16-character ext4 label limit and `_ADMIN` and `_PERSONAL` truncated to the
same label. The page keeps its old filename so links resolve; the old names
are still recognised.

## How it is used

`persist_bind_mounts.py` bind-mounts `/etc/baseline`, `/var/lib/baseline` and
`/var/log/baseline` from the active persona's volume, so existing modules keep
their absolute paths. `switch_active_persona` unmounts the current persona,
requires the caller to have already authenticated, then mounts and rebinds the
new one. If mounting fails, [recovery mode](../../baseline/lib/recovery_mode.py)
is entered.

## Status

| Item | Status | Verified | Evidence |
|---|---|---|---|
| Per-persona volumes and bind redirects | MVP completed | unit tests | `persist_bind_mounts.py`; says itself not yet run on real hardware (DR 62) |
| Persona switch | MVP completed | unit tests | `switch_active_persona` |
| Label collision on the real Baseline drive | open | real hardware | partitions 5 and 6 both truncate to `USER_PERSISTENCE`; fix is the relabel plan, not applied |
| Cross-persona access gated by a second passphrase | On roadmap | none | DR 76 describes it; not checked here |
