# Decision record: LXC provisioning primitive built generic, app choice still deferred

Status: **implemented, unit-tested (10 new tests, 654/654 suite
passing), not yet re-verified against a real Proxmox host. Which
specific always-on service to actually run this way is still not
decided** - see "Still deferred" below.

## Resolving the blocker without guessing the answer

Decision record 34 deferred LXC utility-container vendoring pending a
concrete target service (which app to actually run). Asked to keep
going on that item without a target yet named, the honest move is the
one already used for the VM half: build the generic
create/start/stop/destroy primitive first, independent of any specific
app - the same shape `vm_provision.py` took relative to Track A4's
"any OS" goal. Picking an app-installer script to vendor on top of
this remains a separate, smaller follow-up once a target exists; this
record does not guess one to unblock itself.

## What was built

`baseline/lib/pct_provision.py` - `create_ct`/`start_ct`/`stop_ct`/
`destroy_ct`/`list_available_templates`, each with its own pure argv
builder, following the exact same convention as `vm_provision.py`
(`Runner`-injected, `CommandResult` return shape, `repair.py`'s
established boundary). `next_free_vmid`/`next_free_vmid_argv` are
imported directly from `vm_provision` rather than reimplemented - VMID
is one shared namespace across both VMs and containers in Proxmox, so
this is reuse of a real fact, not incidental duplication.

## What this deliberately does not do

- **No safe-retire helper.** `vm_provision.retire_vm_preserving_persistence`
  encodes a sequence Track A4 proved by hand for VMs (reassign the
  disk before destroying). No equivalent has ever been proven for an
  LXC container's mount point in this project, so `pct_provision.py`
  does not assert or guess at that command shape. If a persistence-
  backed container is ever actually built, that sequence needs its own
  real proof first, the same way A4's VM sequence got one - not a
  copy-pasted guess from the VM module.
- **No app-installer vendoring.** This module has no opinion about
  what runs inside the container. Vendoring or porting a specific
  community-scripts/ProxmoxVE installer (or writing a Baseline-native
  one) is real, separate work once a target is named.
- **Not re-verified against a real Proxmox host.** Same caveat as
  `vm_provision.py` - proven against `FakeRunner` only so far.

## Still deferred

Which service actually runs in an LXC container this way remains an
open question for the user to answer - candidates raised so far in
this project's own conversation include a future Guardian instance
(log-noise triage, per the earlier cross-session design review) and
any of community-scripts/ProxmoxVE's existing app installers (Pi-hole,
Home Assistant OS, etc.). Nothing here picks one.

## Verification performed before this commit

- RED confirmed first: `ModuleNotFoundError: No module named
  'pct_provision'` before any implementation existed.
- 10 new unit tests, all passing - including one asserting
  `next_free_vmid`/`next_free_vmid_argv` are the literal same objects
  imported from `vm_provision`, not reimplemented copies.
- Full suite: 654/654 passing (644 before this change), no
  regressions.
- `pct_provision.py` byte-compiles clean.
