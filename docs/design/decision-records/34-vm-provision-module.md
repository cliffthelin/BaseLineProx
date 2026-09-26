# Decision record: full-VM provisioning generalized into reusable code (Track A6 follow-on)

Status: **implemented, unit-tested (15 new tests, 644/644 suite
passing), not yet re-verified against a real Proxmox host.** Track A4
proved every operation this module encodes by running the equivalent
commands manually and observing the real result; this record turns
that proven-by-hand sequence into committed, reusable, Runner-tested
code for the first time - closing the gap the 2026-09-26 design review
flagged ("no code path that creates, starts, stops, or configures a
VM/container... grepping the tree found nothing").

## LXC vs. full VM - resolved, not deferred

Asked which primitive to vendor first (the Proxmox VE Helper-Scripts
ecosystem, or a Baseline-native equivalent), the honest technical
answer settled it: LXC (`pct`) containers share the host kernel and
can only ever run Linux. This project's own stated goal - "spin up any
OS and collect data from it" - contradicts that outright. Full VMs
(`qm`) are the only primitive that can satisfy it. LXC remains the
right *complementary* tool for a different job (lightweight, always-on
Linux utility services) and is being scoped separately, not built
here - see "Deferred, explicitly" below.

## What was built

`baseline/lib/vm_provision.py` - every operation Track A4 already
proved by hand, as pure argv-building functions (testable with no real
`qm`/`pvesh`) plus thin `Runner`-executed wrappers (goes through the
same injectable subprocess boundary `repair.py` established, matching
`proxmox_vm_metrics.py`'s read-only half of this same convention):

- `next_free_vmid` / `create_vm` / `attach_persistence_disk` /
  `start_vm` / `stop_vm` - the create-and-configure half of A4's
  manual sequence.
- `retire_vm_preserving_persistence(runner, old_vmid, new_vmid, *,
  unused_key)` - the exact ordering A4 discovered was required the
  hard way: `qm set --delete` alone leaves a persistence-backed disk
  still "owned" by the doomed VMID (`qm destroy` would delete it too -
  confirmed via `qm help destroy`'s own text at the time), so the disk
  is always reassigned to a fresh VMID via `qm disk move <vmid>
  <unusedN> --target-vmid <new_vmid>` (a real `lvrename`, not a copy)
  *before* the original is destroyed - and the original is never
  destroyed at all if that reassignment fails. Two of the 15 new tests
  exist specifically to prove the negative: the destroy argv is never
  even attempted when reassignment fails, and a reassignment success
  followed by a destroy failure is reported accurately (persistence
  is safe either way, but the operator needs to know the VM itself
  didn't actually go away).

## What this deliberately does not do yet

- **Not wired into `bin/baseline` or any console command.** This is
  the reusable primitive, not yet an operator-facing "spin up a VM"
  flow - that wiring is a natural next step once a concrete first use
  case is chosen (e.g. a console command mirroring A4's own two
  example VMs).
- **No ISO/ID selection helper.** `iso` is currently just a string the
  caller supplies (e.g. `"local:iso/debian-12.iso"`) - listing what
  ISOs are actually available on a given host (`pvesm list local`)
  is a small, real follow-up, not built here.
- **Not re-verified against a real Proxmox host in this pass.** The
  argv shapes match Track A4's own real, working commands from that
  track's live proof, but this specific committed code has only been
  run against `FakeRunner` so far - the natural next verification step
  is a real `create_vm`/`retire_vm_preserving_persistence` round trip
  on real hardware, the same discipline every other real-hardware
  track in this project has followed.

## Deferred, explicitly (not silently dropped)

Asked to pursue all three streams from the review - full-VM
provisioning (this record), LXC utility-container vendoring, and
scoping a cross-hypervisor (cloud-init/Ansible) alternative - this
record covers only the first. The other two are real, separate pieces
of work, not smaller footnotes to this one:

- **LXC app-installer vendoring** (community-scripts/ProxmoxVE's `pct`
  category) for a lightweight always-on utility service - needs a
  concrete first target (which service) before there's anything to
  vendor or port.
- **Cross-hypervisor scoping** (cloud-init + Ansible, avoiding
  Proxmox-specific `qm`/`pct` lock-in entirely) - a bigger, different
  effort with no Proxmox-specific shortcuts available; worth its own
  scoping pass before any code, not an extension of this module.

## Verification performed before this commit

- RED confirmed first: `ModuleNotFoundError: No module named
  'vm_provision'` before any implementation existed.
- 15 new unit tests, all passing, using the project's existing
  `tests/unit/fake_runner.FakeRunner` (no new fake-runner
  infrastructure needed) - pure argv-shape assertions for every
  command, plus the two negative-ordering tests described above.
- Full suite: 644/644 passing (629 before this change), no
  regressions.
- `vm_provision.py` byte-compiles clean.
