# Decision record: real QEMU smoke test of vm_scripts.py and quadlet.py - two real bugs found and fixed, one important behavioral finding disclosed

Status: **real QEMU execution, twice (before and after fixes). Genuinely
verified against real Podman, real systemd, a real network fetch, and
real (non-mocked) execution of the actual upstream Helper-Script - not
just against `FakeRunner`. Still not verified against an actual
Proxmox host's real `pct create`/`qm create` - see "What remains
unverified" below.**

## What this is

Asked directly to test records 57/58's work under QEMU rather than
leave it proven against fakes only. Built a disposable smoke-test VM:
Debian 13 (trixie) generic-cloud image, QEMU user-mode networking (real
internet access), a cloud-init seed embedding the actual repo files
(`repair.py`, `quadlet.py`, `vm_scripts.py`, plus `network.py`/
`topology.py`/`ifnet_config.py` as `repair.py`'s own dependencies) byte-
identical to what's on disk - not retyped copies. A driver script
(`test_drive.py`) ran every real-mode function against `repair.RealRunner`
and wrote a structured JSON result to a dedicated second serial port the
host captured to a file.

## Bug 1 (found, fixed): `RealRunner.write_text_atomic` didn't create missing parent directories - `FakeRunner` silently masked this in every existing test

`vm_scripts.run_script()` calls `runner.write_text_atomic(CORE_BUILD_FUNC_PATH, ...)`
to stage the verified `core/build.func` at
`/var/lib/baseline/vm_scripts/core-verified/core/build.func` - a brand
new, multi-level directory on a fresh host. First QEMU run:

```
FileNotFoundError
  File "/opt/baseline/lib/repair.py", line 113, in write_text_atomic
    tmp.write_text(content)
```

Root cause: `repair.RealRunner.write_text_atomic` never created the
parent directory - unlike `append_text` in the same class, which
already does (`Path(path).parent.mkdir(parents=True, exist_ok=True)`).
**`FakeRunner.write_text_atomic` already auto-creates parent dirs**
(`self._mark_parents(path)`), so every one of `vm_scripts.py`'s 13
passing unit tests exercised a code path that behaves differently for
real - a textbook instance of the exact "unit-tested against fakes" vs
"verified on real hardware" gap AGENTS.md warns about, caught only
because this session actually ran it for real instead of stopping at
green fakes.

Fix: `repair.py`'s `RealRunner.write_text_atomic` now mkdirs the parent
first, matching `append_text`'s existing behavior - a general fix
benefiting every caller, not a `vm_scripts.py`-local workaround. New
tests: `tests/unit/test_real_runner.py` (4 tests, using pytest
`tmp_path` - real filesystem I/O confined to an auto-cleaned temp
directory, never a real system path).

## Bug 2 (found, fixed): `systemctl enable` refuses a Quadlet-generated unit outright

`quadlet.write_and_enable()`'s `systemctl enable --now <name>.service`
failed for real:

```
Failed to enable unit: Unit /run/systemd/generator/baseline-smoketest.service
is transient or generated
```

Root cause: Quadlet's own generator (`podman-system-generator`) turns
a `.container` file into a *transient* unit under
`/run/systemd/generator/` at every `daemon-reload`/boot - `systemctl
enable` refuses to write a persistent enablement symlink for a unit it
didn't create as a normal on-disk unit file, and there's nothing for
it to persist anyway: the `.container` file's own `[Install]` section
is honored by the generator itself, every time, automatically.
`enable` was simply the wrong verb, not a stricter version of the
right one - and the same reasoning applies to `stop_and_remove`'s
`systemctl disable --now` (untested failure mode - it happened to
return 0 as a no-op in the first run since nothing had ever actually
enabled, but is equally meaningless for a generator unit).

Fix: renamed `write_and_enable` → `write_and_start`, changed to plain
`systemctl start`; `stop_and_remove` changed to plain `systemctl stop`.
Removing the `.container` source file (unchanged) is what actually
prevents recurrence on the next `daemon-reload`/boot - not a
disable step. All existing tests updated to assert `start`/`stop` and
explicitly assert `enable`/`disable` are never called.

## Important behavioral finding (not a bug in this module - a real property of upstream's script that changes its risk profile)

Re-running after both fixes, `vm_scripts.run_script(runner, "debian-lxc", timeout=90)`
against this same plain (non-Proxmox) Debian VM returned
`outcome: applied` in **8.0 seconds**, having printed `✔️ Updated
Debian LXC` / `✔️ Updated successfully!` and run real `apt` activity
directly on the host. **This was not the expected "clean refusal, no
`pct`/`qm` found" outcome the module's own docstring had assumed before
this test.** Upstream's Helper-Scripts are dual-purpose: the same
script both creates a container (via Proxmox `pct create`) *and*
updates an already-created one - `core/build.func`'s own environment
detection apparently took the "already installed, update in place"
branch when no Proxmox environment was found, rather than erroring.

This is a real, previously-undocumented (in this project) risk: a
curated, pinned, hash-verified script from this manifest can still
mutate whatever host it's actually run against - Proxmox or not -
because upstream's own control flow doesn't fail closed on an
unexpected host. `vm_scripts.py`'s module docstring is updated to
state this plainly rather than leave the earlier, narrower
"unpinned transitive fetch" caveat as the only disclosed risk -
it understated the actual exposure.

## What remains unverified

- No real Proxmox host, no real `pct create`/`qm create` succeeding
  against an actual `pveversion`-visible target. This session's Debian
  VM deliberately has no Proxmox on it; genuinely proving the intended
  "create a real LXC/VM" path needs a real (or nested-QEMU) Proxmox
  target - out of scope for this pass, flagged as the natural next
  step, not silently assumed to work by extrapolation from the
  update-path proof above.
- `pihole-lxc`, `homeassistant-lxc`, `docker-lxc`, `debian-vm`,
  `haos-vm` were fetch+hash-verified as part of the original record 57
  work (see that record) but not executed via `run_script()` in this
  QEMU pass - only `debian-lxc` was.

## Verification performed

- First QEMU run (pre-fix): reproduced both bugs above with real
  tracebacks/error text, captured in this record verbatim - not
  paraphrased from memory.
- Both fixes applied; full fake-based suite re-run: 898/898 passing
  (894 after records 57/58, before this record's own additions - see
  those records for that count). This record adds 4 new tests
  (`tests/unit/test_real_runner.py`, proving the `write_text_atomic`
  fix against a real filesystem) plus renames/updates the existing
  quadlet tests in place (no net new quadlet test count) - 894 + 4 =
  898, matching the number below.
- Second QEMU run (post-fix), fresh disposable overlay from the same
  pristine base image: every one of 17 real assertions passed -
  `is_podman_installed`, `generate_unit`, `write_and_start`,
  `status`/`is_running` (`active`/`True`), the unit file's real
  presence and real removal, `podman ps` actually showing the running
  container and actually showing it gone after `stop_and_remove`,
  real `verify_and_get`/`verify_core_build_func` against the live
  network, real refusal-without-fetching for an unknown script id, and
  the `run_script` timing/outcome described above.
- Disposable test VM and its disk images deleted after this record was
  written - matches this project's established disposable-QEMU-proof
  retention discipline (milestone-2-gui-plan.md).
