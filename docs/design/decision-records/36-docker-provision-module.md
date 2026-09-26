# Decision record: Docker provisioning module - compatibility beyond LXC

Status: **implemented, unit-tested (10 new tests, 664/664 suite
passing). Not verified against a real Docker daemon at all** - see
"Why nothing here has run for real" below, which is a genuine
environment limitation, not a deferred choice.

## The question this answers

Asked to keep working on the two open gaps from records 34/35 (a
target service for the LXC primitive; real-hardware verification), the
user added a specific new constraint: "I want compatibility beyond
LXC." `pct_provision.py` (record 35) is Proxmox-native - a container
built for it only ever runs on Proxmox's `pct`. Docker resolves this
directly: an image built once runs identically on a Proxmox VM,
bare-metal host, or the cloud.

The earlier scoping document
(`cross-hypervisor-provisioning-scoping.md`) recommended against
building a general hypervisor-agnostic *abstraction* layer (cloud-init
+ Ansible) - that recommendation stands, and this module doesn't
contradict it. Docker is a narrower, already-solved piece of the same
underlying idea (portable workload packaging, not portable VM/CT
*creation*) - genuinely different scope, not a reversal.

## What was built

`baseline/lib/docker_provision.py` - `create_container`/
`start_container`/`stop_container`/`remove_container`/`is_running`,
each with its own pure argv builder, following the exact same
convention as `vm_provision.py`/`pct_provision.py` (`Runner`-injected,
`CommandResult` return shape re-exported from `vm_provision` rather
than redefined a third time). Wraps the `docker` CLI directly, no SDK
dependency - matches this project's stdlib-only, subprocess-based
convention everywhere else.

Still true here, same as the LXC half: **no target service is named.**
This module has no opinion about what image actually runs - it exists
so a target can run portably the moment one is chosen, the same
resolution record 35 used for `pct_provision.py`.

## Why nothing here has run for real

Checked directly in this session, both came back negative:

- **No Proxmox host reachable at all.** This session's environment
  (`cane-System-Product-Name`, a plain Ubuntu dev machine) has no
  `qm`/`pct`/`pvesh` installed, and `~/.ssh/config` has no entry
  pointing at a Proxmox host. Whatever machine Track A1-A5's real
  hardware work ran against in earlier sessions is not reachable from
  this one.
- **Docker's daemon isn't installed here, only the client.**
  `docker ps` fails with `dial unix /var/run/docker.sock: connect: no
  such file or directory`, and `systemctl status docker` reports the
  unit doesn't exist at all - this is a from-scratch daemon
  install/start, not a "just start the service" fix, and starting a
  system service is exactly the kind of system-state change this
  project's own safety discipline says to confirm before doing, not
  assume.

Both of these are named explicitly rather than silently worked around,
matching this project's own honesty convention (e.g. Track B3's DRM
issue being left unresolved and stated as such, never claimed solved).
Real verification of all three provisioning modules
(`vm_provision.py`, `pct_provision.py`, `docker_provision.py`) is
blocked on one of: real Proxmox host access from a session that can
reach it, or explicit permission to install/start a Docker daemon on
this dev machine for the Docker half specifically.

## Verification performed before this commit

- RED confirmed first: `ModuleNotFoundError: No module named
  'docker_provision'` before any implementation existed.
- 10 new unit tests, all passing, against `FakeRunner` only - no real
  `docker` daemon exists in this environment to test against, stated
  plainly rather than glossed over.
- Full suite: 664/664 passing (654 before this change), no
  regressions.
- `docker_provision.py` byte-compiles clean.
