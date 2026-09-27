# Decision record: vm_scripts/pct_provision-vm_provision unification, quadlet.py rootless mode implemented, three more Helper-Scripts run under real QEMU

Status: **all three implemented and unit-tested (922/922 full suite). The unification bridge and rootless mode are proven against `FakeRunner` only. Three additional Helper-Scripts (`docker-lxc`, `debian-vm`, and the `run_script_and_adopt` path against `pihole-lxc`) were run for real under QEMU, adding real evidence beyond decision record 59's single data point.**

## What this resolves

Direct instruction to work items #14-16 from `docs/design/v0.1-work-queue.md` (item #17 remains explicitly blocked - no physical access to real target hardware from this session, unchanged).

## Item #14: vm_scripts.py / pct_provision.py / vm_provision.py unification

Record 57 flagged two parallel guest-creation paths as a real, undosed seam. Full unification (routing creation itself through `pct_provision.create_ct`) isn't realistically achievable - upstream's Helper-Scripts contain real install logic (template selection, network wait-up, package install) that would have to be reimplemented by hand to intercept, defeating the reason to reuse them at all.

What's real and achievable: `vm_scripts.run_script_and_adopt()` captures the VMID Proxmox will assign via `vm_provision.next_free_vmid` **before** invoking the script, then returns an `AdoptedGuest` that `start_adopted`/`stop_adopted`/`destroy_adopted` dispatch to `pct_provision.py`'s or `vm_provision.py`'s own tested functions, by `kind`. Creation stays on this module's own path (unavoidable); every lifecycle operation after creation goes through Baseline's existing primitives, not a third command shape.

**Disclosed limitation, not hidden**: querying `/cluster/nextid` doesn't reserve it - there's no lock between this read and the Helper-Script's own internal read of the same endpoint. In this project's established single-operator, sequential-use context, the two reads land on the same VMID in practice; this is not a concurrency guarantee, and `run_script_and_adopt`'s own docstring says so plainly.

**Real gap found and fixed while wiring this up**: `vm_provision.py` had `destroy_vm_argv` (the pure argv builder) but no plain Runner-executed `destroy_vm` - only the persistence-preserving `retire_vm_preserving_persistence`, which doesn't fit a guest that never had persistence attached (forcing an unused disk-reassignment step that doesn't apply). Added `vm_provision.destroy_vm(runner, vmid, *, purge=True)`, mirroring `pct_provision.destroy_ct`'s existing shape, with an explicit docstring warning it must never be called on a persistence-backed VM.

## Item #15: three more curated scripts run under real QEMU

All 6 curated manifest entries' pins were first re-verified for real against live upstream (all matched - the pinned-commit content is immutable, as designed). Then, under a fresh disposable QEMU VM:

- **`docker-lxc`** - also hit the "no interactive terminal" condition `debian-lxc` did, but took a **different real outcome**: exit 113, "General error / Operation not permitted," correctly reported as `refused`. Confirms behavior is not uniform across scripts even under the same general condition.
- **`debian-vm`** - a genuinely different code path: failed in under 1 second with `pveversion: command not found`, exit 127. VM-kind (`vm/*.sh`) scripts checked so far do not share the LXC-kind update-in-place fallback at all - they hard-require `pveversion` and fail closed immediately without it.
- **`run_script_and_adopt` against `pihole-lxc`** - correctly refused before ever reaching `bash`, because the real `pvesh get /cluster/nextid` call fails cleanly on this non-Proxmox host (`pvesh` not found). Confirms the new adoption bridge's error handling for real, not just against `FakeRunner`.

`vm_scripts.py`'s module docstring rewritten to state the honest, now-multi-data-point summary: behavior genuinely varies by script and by kind - "always fails closed" and "always mutates the host" are both wrong generalizations. `homeassistant-lxc` and `haos-vm` remain fetch+hash-verified but not yet executed under QEMU - said plainly, not implied otherwise.

## Item #16: quadlet.py rootless mode

Record 58 flagged `ContainerSpec.rootless=True` as a field with no real branch behind it - always wrote to `/etc/containers/systemd` regardless. Now real:

- `ContainerSpec` gained `.user` (the target unprivileged user).
- `unit_path()` takes `rootless`/`user_home` and returns the real per-user Quadlet path (`~/.config/containers/systemd/`) - `user_home` must be resolved for real via `_lookup_user_uid_and_home` (a real `getent passwd` call), never guessed as `/home/<user>` (wrong for LDAP/NFS-homed accounts).
- `_systemctl_prefix()` returns `runuser -u <user> -- env XDG_RUNTIME_DIR=/run/user/<uid> systemctl --user` for rootless mode - the real invocation shape rootless Quadlet needs (a root-invoked `systemctl --user` alone can't find that user's session bus without `XDG_RUNTIME_DIR` set explicitly).
- `write_and_start`/`stop_and_remove`/`status`/`is_running` all take the new params and refuse cleanly (never guess) when `rootless=True` but `.user`/`user` is unset, or when the user doesn't resolve.

**Real design correction made while implementing this, not merely documented as a caveat**: `ContainerSpec.rootless`'s default was `True` with no real behavior behind it. Since rootless mode has no sensible universal default user, and Baseline itself runs as root today, keeping `True` as the default would mean the *default* `ContainerSpec()` silently required an unstated prerequisite (`loginctl enable-linger`). Changed the default to `False`, matching what's actually true right now - existing callers/tests were unaffected by this (they never set `rootless` explicitly and expected root-mode `systemctl` calls, which is exactly what the corrected default now produces without any test changes).

## Verification performed

- RED-then-GREEN for all three: `test_vm_provision.py` gained 3 tests for `destroy_vm`; `test_vm_scripts.py` gained 9 tests for the adoption bridge; `test_quadlet.py` gained 8 tests for rootless mode.
- Full suite: 922/922 passing (902 before this record - 3 + 9 + 8 = 20 new tests, matches exactly).
- Real QEMU pass (fresh disposable Debian VM, same discipline as records 59/60): all three real scripts executed, real outcomes captured verbatim above - not paraphrased or assumed.
- Disposable QEMU disk images and the re-downloaded base cloud image deleted after verification, per this project's established retention discipline.
- **Item #17 unchanged, still blocked**: running `baseline-prepare-real-install-iso` against actual target hardware needs physical presence this session does not have.
