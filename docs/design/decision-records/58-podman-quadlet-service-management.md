# Decision record: Podman + Quadlet as the service-management layer for containerized apps (Track B4)

Status: **implemented, unit-tested only (13 new tests here, 13 more in
record 57 - 894/894 full suite passing at that point, up from 868
before this pair of changes. See record 59 for a real bug this pass's
fake-based tests did not catch, found via QEMU and fixed there,
including a rename of this record's `write_and_enable` to
`write_and_start`). Not run against real Podman, real systemd, or a real host
- `podman --version`/`systemctl` calls are FakeRunner-scripted only in
this pass.**

## Why Podman + Quadlet, not raw `podman run` + a hand-written unit, and not Docker

Red Hat's 2026 `fedora-bootc`-based agentic-OS prototype (Fedora
Hummingbird) independently converged on the same combination for the
same class of problem - rootless Podman for isolation, Quadlet for
service lifecycle - worth citing as external validation, not the
reason by itself. The actual reasons, specific to this project:

- **Quadlet `.container` files are declarative and versionable** -
  `systemd-quadlet-generator` turns them into ordinary systemd units at
  `daemon-reload` time, so every existing Baseline convention for a
  service (`systemctl enable/start/stop/status`, `journalctl` for
  logs) keeps working unchanged. A hand-written unit calling `podman
  run` directly would need its own bespoke stop/cleanup semantics
  (`podman run` without `--rm` leaves a stopped container behind on
  every service restart) - Quadlet's generator handles this correctly
  by construction.
- **Rootless-first by default** (`ContainerSpec.rootless = True`)
  matches the "never trust a generic privileged daemon by default"
  instinct milestone-2-gui-plan.md already established for the GUI
  brokers - Podman itself (a distro-vetted, audited package) is the
  one already-accepted exception to that instinct, not a new one.
- **Distinct from `docker_provision.py`'s job.** That module wraps the
  `docker` CLI for portable, cross-hypervisor container images (its own
  docstring: "a Docker image runs identically on a Proxmox VM,
  bare-metal, or the cloud"). This module is about how Baseline itself
  manages a container **as a host service** (start on boot, restart on
  crash, `systemctl status` parity with every other Baseline unit) -
  a different question from "which container runtime builds/runs the
  image." The two are not in tension and don't need to be unified: an
  image built/run via `docker_provision.py` could still, separately, be
  wrapped in a Quadlet unit for host-level lifecycle management if
  Podman is what's installed - that integration is real, separate
  follow-up work, not assumed solved here.

## What was built

- `baseline/lib/quadlet.py` - `ContainerSpec` (name, image,
  description, command, volumes, environment, network, publish,
  rootless, auto_update), `generate_unit()` (pure - produces the actual
  Quadlet INI content), `is_podman_installed()`, `write_and_start()`,
  `stop_and_remove()` (stops + removes the unit file only - never
  touches the image or any named volume, matching
  `repair_rollback.py`'s "never destroy data the operator didn't
  explicitly ask to lose" posture), `status()`/`is_running()` (return
  systemd's own `is-active` vocabulary unchanged rather than inventing
  a parallel one).
- `provision.sh` - installs `podman` via `apt-get`, creates
  `/etc/containers/systemd`, deploys `quadlet.py`, and the fail-closed
  verification block now checks `podman` is on `PATH` and the Quadlet
  unit directory exists before any tty1/getty-affecting step, matching
  every other package this script installs.

## What this deliberately does not do yet

- No app is actually wired to a Quadlet unit by this record - this is
  the generic primitive only, the same "build the primitive before
  guessing the target" discipline records 34/35 already used for
  `vm_provision.py`/`pct_provision.py`.
- No rootless-user/socket-activation setup beyond the `rootless=True`
  default field on `ContainerSpec` - actually running Podman rootless
  requires per-user lingering (`loginctl enable-linger`) and a
  user-level Quadlet directory (`~/.config/containers/systemd/`) that
  this record's `write_and_start()` does not yet branch on; today it
  always writes to the root-level `/etc/containers/systemd`. A real
  rootless deployment needs that branch added before the field means
  anything operationally - flagged here rather than silently assumed
  working.

## Verification performed before this commit

- RED confirmed first: `ModuleNotFoundError: No module named
  'quadlet'` before any implementation existed.
- 13 new unit tests (`tests/unit/test_quadlet.py`), all passing -
  `generate_unit()`'s purity (identical output for identical input,
  every optional field present when supplied), the podman-missing
  refusal path, the full write/reload/start success path, a
  daemon-reload-failure path, and `stop_and_remove()` genuinely
  removing the unit file (verified against `FakeRunner`'s real
  in-memory file removal, not just asserting a `rm` argv was
  attempted).
- Full suite: 894/894 (868 before this pair of changes) - see record
  57 for the vm_scripts.py half's 13 tests; no regressions from either
  change. (See record 59: a real QEMU test found `systemctl enable`
  fails on a Quadlet-generated unit - fixed there, function renamed to
  `write_and_start`.)
- **Not verified**: no real Podman install, no real `systemctl
  daemon-reload`/`enable --now`, no real container has been started by
  this code on any real host.
