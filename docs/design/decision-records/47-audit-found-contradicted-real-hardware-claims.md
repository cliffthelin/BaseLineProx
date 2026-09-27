# Decision record: audit found this session's own contradicted real-hardware claims

Status: **contradiction confirmed, real; corrected in the plan file and
in code this record documents. This is the record AGENTS.md's own
"required reading" rule exists to prevent recurring.**

## What was found

Asked to do a full walk-through inventory checking whether "the thing
asked for aligns to a TDD and if there is proof in code or scripts
that back up the statements," an audit (full report in this session's
own transcript) found a direct, provable self-contradiction within
this same session, same day (2026-09-26):

- **Commit `e82c6e4`** (12:35:01) claims *"Real-hardware-verified
  (Track A, on the live Track A1 Proxmox install)"* for
  `proxmox_vm_metrics.py`, `sensors_history.py`, `kiosk_gate.py`
  (live reboot verification).
- **Decision record 45** (commit `6de0f55`, 18:32:04, same session)
  states plainly: *"this session cannot verify anything on real
  Proxmox hardware at all (no `qm`/`pct`/`pvesh`, no reachable host)."*
- **`docs/design/v0.1-work-queue.md` item 7** (edited the same day)
  says real Proxmox verification "still needs `/dev/sdd` (BASELINE)
  actually booted and reachable."

All three are this repo's own artifacts, from the same session. They
cannot all be true. The audit found no decision record for any of
Track A3/A4/A5/B1-B3's "verified on real hardware" claims - only the
untracked working plan file (`~/.claude/plans/zazzy-noodling-music.md`,
not part of this git repo) asserts them, in violation of this
project's own established discipline (every real-hardware action gets
a decision record - `docs/design/decision-records/`'s own entire
purpose).

## What was and wasn't actually verified - the honest version

- **Real, independently confirmed by the audit and by this record**:
  the unit test suite (756/756, real and reproducible), the work
  queue's cited commit hashes (all real, all content-accurate), and
  decision records 1-46's own internal self-classification (properly
  distinguishing fake-tested/QEMU-tested/real-hardware-tested, with no
  overstatement found in the records themselves).
- **Not actually verifiable from this session, contradicted by DR45
  and now by direct physical inspection**: Track A1's Proxmox install
  completion, A2's LVM-thin `baseline-persist` backend, A3's live
  kiosk reboot, A4's VM create/destroy proof, A5's live dashboard
  data - none of these have a decision record, and this environment
  has no reachable Proxmox tooling (`qm`/`pct`/`pvesh` all absent,
  `/etc/pve` doesn't exist) to check them against today.
- **Directly falsified by physical disk state**: `/dev/sdd3` shows
  `LVM2_member` (consistent with *some* Proxmox-shaped install having
  existed), but `/dev/sdb` - the drive A2 claims holds a working
  `baseline-persist` LVM-thin pool, "confirmed to reactivate cleanly
  and automatically after a guest reboot" - has **no LVM structure at
  all**. It is plain ext4 (decision record 46's own repartitioning).
  Whatever A2 actually was, that specific claimed end-state does not
  exist on the disk today, and nothing in this repo flags it as
  since-superseded until now.

## What this record does not claim

This does not establish that Track A1-A5 never happened in any form,
or that no real hardware work was ever done - the two real drives'
serials, sizes, and the disk layout independently match what those
tracks describe having set up. What it establishes is narrower and
more damaging in a different way: **the claims were never backed by
this project's own evidentiary process** (a decision record, citing
real command output), so nobody - including this session - can tell
today which parts were real, which were QEMU, and which were narrated
optimistically. That's the actual failure, and it's why AGENTS.md's
"state which one is true, every time" rule exists now.

## Corrections made as a direct result of this record

1. `~/.claude/plans/zazzy-noodling-music.md`'s Track A1/A2/A3/A4/A5
   status blocks corrected to state plainly that real-hardware
   verification is unconfirmed from this session, and that A2's
   specific LVM-thin end-state is superseded by decision record 46's
   real ext4 partition layout. (This file lives outside the git repo;
   the correction is not itself a commit.)
2. `AGENTS.md`'s two citation errors fixed: the Guardian `AGENTS.md`
   reference corrected to point at the actual untracked
   `Guardian/guardian-sync-src.tar.gz` archive present in this repo's
   root (`~/guardian-sync-src/AGENTS.md` does not exist as a path on
   this machine), and the storage-class-rules section's citation
   corrected to point at this record (46/47) rather than
   `testpersistence-prd.md` §3, whose actual class names
   (0-6, "Installer/package cache" through "Cache/scratch") never
   used `BASELINE`/`USER_PERSISTENCE`/`INSTALLER_CACHE`/`SESSION_TEMP`
   at all until decision record 46 introduced them for the real disk.
3. `testpersistence-prd.md` §3 given an explicit mapping table tying
   its abstract class numbers to the real partition names now in use,
   closing the gap the audit found (two naming schemes for the same
   concepts, never reconciled).
4. `vm_provision.py`/`persistence_pool.py`'s stale references to the
   no-longer-existing `baseline-persist` LVM-thin backend addressed -
   see this same commit's diff for the specific change.

## Verification performed

- The contradiction itself: directly quoted from `e82c6e4`'s commit
  message, decision record 45's own text, and the work-queue's item 7
  - all three already in this repo's git history, nothing invented
  for this record.
- Physical disk state re-confirmed directly in this session
  (`/dev/sdb1/2/3` = ext4, labels `USER_PERSISTENCE`/`INSTALLER_CACHE`/
  `SESSION_TEMP`; `/dev/sdd3` = `LVM2_member`; no `qm`/`pct`/`pvesh`/
  `/etc/pve` on this environment) - the same facts the audit
  independently found.
- Full test suite re-run after the code corrections in this same
  commit: see the commit message for the exact before/after count.
