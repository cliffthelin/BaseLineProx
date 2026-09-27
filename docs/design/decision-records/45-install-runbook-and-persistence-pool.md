# Decision record: the definitive install runbook, and a real persistence-pool module to close the second lost-commands gap

Status: **`docs/INSTALL.md` written (new); `persistence_pool.py`
implemented and unit-tested (16 new tests, 756/756 suite passing).
Neither has been run end-to-end against real hardware** - this record
documents closing the *documentation and code* gap an audit found,
not a claim that the gap is closed on real hardware.

## What prompted this

Asked directly whether a physical drive was ready to boot, and told
the audit finding straight: this session cannot verify anything on
real Proxmox hardware at all (no `qm`/`pct`/`pvesh`, no reachable
host). The user's response reframed the actual problem: **"what we
have committed to GitHub - how are we telling anyone including
ourselves how to load it and use it? Follow those directions and if
they are insufficient... make them complete now."**

An audit (this session, full transcript in the agent's own report)
found the honest answer was: **no single document does this, and two
of the most physically consequential steps - the real Proxmox install
and the persistence pool's creation - have zero reusable code or
recorded commands anywhere.** Both exist only as prose narration in
`docs/SESSION_HANDOFF.md`, describing what was done, not how to
reproduce it.

## What was built

- **`docs/INSTALL.md`** - the single, authoritative, step-by-step
  runbook this project didn't have. Every step states plainly whether
  it's verified on real hardware, verified only under QEMU, or brand
  new and unverified - a table at the top, not buried in prose. It is
  explicitly designed to be **edited in place** as steps are actually
  run and corrected, unlike the append-only changelog or the
  point-in-time decision records - the whole reason it's being written
  is that those two formats are exactly what let this gap form in the
  first place (real knowledge existed, narrated once, then buried).
- **`baseline/lib/persistence_pool.py`** - `deactivate_stale_vgs`
  (by exact VG UUID, never by name alone - Track A2's own narrated
  disambiguation reasoning, now encoded as a real, tested function
  instead of a sentence), `create_thin_pool` (the `pvcreate` ->
  `vgcreate` -> `lvcreate` sequence, stopping at the first failure),
  `register_with_proxmox` (`pvesm add lvmthin`). Same `Runner`-injected,
  `CommandResult`-returning convention as `vm_provision.py`/
  `pct_provision.py`/`docker_provision.py`.

## Why this is a reconstruction, not a recovery - stated as loudly as possible

Asked whether the exact original commands were recoverable (shell
history on the physical machine, notes), the honest answer was "not
sure - check when you get access." **This module and this runbook do
not claim to reproduce what Track A2 actually typed.** They encode a
defensible, real-tool-based procedure consistent with what the
narration describes (exact-UUID VG disambiguation, LVM-thin, `pvesm
add lvmthin`), built the same way `vm_provision.py` was built from
Track A4's own narration earlier this session. Both `INSTALL.md` and
`persistence_pool.py`'s own docstrings say this explicitly, more than
once, specifically because a reader skimming past that caveat and
running destructive LVM commands against the wrong device is a real,
serious risk this record is trying to head off.

## The real Proxmox-install gap - resolved further than expected

Auditing `drive_setup_install.py` to write `INSTALL.md`'s Step 4 found
the gap is smaller than the audit implied: `build_sparse_install_
invocation`'s `target_image: Path` parameter is interpolated directly
into `-drive file={target_image},...` - QEMU accepts a real block
device path exactly as it accepts a sparse file path, and the
project's own working plan already stated this exact reuse as the
intended design ("passing the validated real device path as
target_image - skip create_sparse_target"). Separately,
`drive_setup_answer.py` wraps Proxmox's own official
`proxmox-auto-install-assistant`, which produces a genuinely real,
standard bootable ISO usable on real hardware - not a QEMU-specific
artifact. **No new code was needed for this half** - `INSTALL.md`'s
Step 4 documents combining existing, already-real code correctly for
the first time, and flags one real open question (`--fetch-from iso`
vs. `http` for a real bare-metal boot with no network answer server)
rather than guessing at it.

## What this still does not do

- Neither `INSTALL.md`'s Step 4 (real Proxmox install) nor Step 7
  (`persistence_pool.py`) has been run once, for real, against any
  hardware. The status table at the top of `INSTALL.md` says so
  plainly and is meant to be corrected in place the first time someone
  actually runs these steps - this record does not duplicate that
  table's content, since `INSTALL.md` is the thing meant to stay
  current, not this record.
- Does not resolve queue item 7 (real-hardware verification access) -
  still blocked on the same thing it always was. What changes is that
  there's now a real runbook and real code ready the moment access
  exists, instead of nothing.
- Does not recover the LVM-reclaim note from the original 2026-09-20
  handoff (queue item 6) - genuinely unrecoverable without checking
  the physical machine directly, per the user's own answer. This
  record's `persistence_pool.py` may or may not be what that note
  referred to; nobody can say for certain.

## Verification performed before this commit

- RED confirmed first: `ModuleNotFoundError: No module named
  'persistence_pool'` before any implementation existed.
- 16 new unit tests: pure argv/output-parsing (VG-listing, stale-UUID
  detection excluding the kept UUID, pool-creation command sequence,
  Proxmox-registration argv) and Runner-executed operations (stopping
  at the first failing command in a multi-command sequence, reporting
  real failure details, the "nothing stale" no-op case).
- Full suite: 756/756 passing (740 before this change), no
  regressions.
- `persistence_pool.py` byte-compiles clean.
- `docs/INSTALL.md` is documentation only - no automated verification
  applies to it beyond human review of its own cited function
  signatures against the real modules they name.
