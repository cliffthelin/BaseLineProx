# Decision record: app-specific LXC/VM provisioning via pinned + sha256-verified community-scripts/ProxmoxVE Helper-Scripts

Status: **implemented, unit-tested only (13 new tests here, 13 more in record 58 - 894/894 full suite passing at that point, up from 868 before this pair of changes; see record 59 for two real bugs this pass's tests didn't catch, found via QEMU, bringing the current total to 898/898). Not run against a real Proxmox host, real `pct`/`qm`, or a real network fetch from inside the app - the pin/hash values themselves were computed by actually downloading and hashing the real upstream files during this session (real evidence, not invented), but executing the resulting code end to end on real hardware has not happened.**

## What this resolves

Decision record 35 (`pct_provision.py`) built the generic
create/start/stop/destroy LXC primitive, then explicitly deferred one
item: *"LXC app-installer vendoring (community-scripts/ProxmoxVE's
`pct` category) for a lightweight always-on utility service - needs a
concrete first target (which service) before there's anything to
vendor or port"* - and named its own candidates: *"a future Guardian
instance... and any of community-scripts/ProxmoxVE's existing app
installers (Pi-hole, Home Assistant OS, etc.)"*.

This record picks exactly those named candidates (plus a plain Debian
base case for both LXC and full-VM) as the first concrete targets, and
closes the deferred item - but via a pinned + hash-verified integration,
not raw vendoring or a blind `bash -c "$(curl ...)"` against a moving
branch.

## Real security finding made during this work: two-stage (not one-stage) verification is required

Naive plan: pin the entry-point script (`ct/docker.sh` etc.) to one
commit, sha256-verify it, done. Actually inspecting the fetched script
(not assumed) found it sources a second file from a *different*
upstream repo at runtime: `core/build.func`
(`community-scripts/core`), via `source "$_cs_boot" 2>/dev/null ||
source <(curl -fsSL "${COMMUNITY_SCRIPTS_CORE_URL:-...}")`. Pinning only
the entry-point script leaves this second, unpinned, live `main`-branch
fetch completely open - a false sense of closure.

Fix: `vm_scripts.py` pins and sha256-verifies `core/build.func` too,
and stages the verified copy locally, then sets
`COMMUNITY_SCRIPTS_CORE_DIR` (upstream's own documented override hook,
read directly from the fetched script's own `_cs_boot` line - not
invented) to point the entry-point script at the verified local copy
instead of a live fetch.

**This still does not achieve full closure, and the module docstring
says so explicitly.** `core/build.func` itself contains a generic
`_cs_download`/`_cs_remote_url` mechanism (confirmed by grep against
the real fetched file, not assumed) that can source further remote
files at runtime, whose exact set depends on control flow (which
app/OS) this integration does not statically enumerate. Per AGENTS.md's
"no placeholders" and "state which claim is true" rules: this is a
disclosed, real, open gap - not swept under a "pinned and verified"
claim that would overstate what's actually closed. `run_script()` is
documented as operator-invoked-only for exactly this reason; it must
never be wired to an automatic trigger or invoked by the harness on its
own initiative until a fully vendored, network-isolated execution
environment closes the remaining gap (the same lesson OpenHands'
docker-sandboxed execution model applies to agent-adjacent code
execution generally).

## Relationship to pct_provision.py / vm_provision.py - a real seam, not unified

`vm_scripts.run_script()` does **not** call `pct_provision.create_ct`
or `vm_provision.create_vm`. The upstream Helper-Script calls
`pct create`/`qm create` internally, with its own opinionated defaults,
which Baseline neither sees nor controls at that point. Two parallel
paths to create a guest now exist in this codebase on purpose:
Baseline-native minimal primitives (record 34/35) for when Baseline
wants full control of the command shape, and this pinned-upstream-script
path for "give me a working Pi-hole/Home Assistant/Docker host in one
call" convenience. Unifying them - e.g. teaching this module to drive
`pct_provision.py`'s primitives instead of upstream's internal
`pct create` - is real, separate follow-up work, not assumed solved
here.

## What was built

- `baseline/lib/vm_scripts.py` - `SCRIPT_MANIFEST` (six curated
  entries: `debian-lxc`, `docker-lxc`, `homeassistant-lxc`,
  `pihole-lxc`, `debian-vm`, `haos-vm`), `list_scripts()`,
  `verify_and_get()`, `verify_core_build_func()`, `run_script()`. Every
  `sha256` in the manifest was computed by this session directly
  downloading the real file from
  `raw.githubusercontent.com/community-scripts/ProxmoxVE/<PINNED_COMMIT>/<path>`
  and `raw.githubusercontent.com/community-scripts/core/<CORE_PINNED_COMMIT>/core/build.func`,
  then `sha256sum`-ing the actual bytes - not invented, not copied from
  an unverified secondary source.
- `tests/unit/fixtures/pve_ct_debian_pinned.sh`,
  `tests/unit/fixtures/pve_core_build_func_pinned.sh` - byte-identical
  copies of those real, MIT-licensed upstream files at the pinned
  commits, used so the test suite's hash-match assertions are proven
  against genuine content, not a fabricated stand-in.
- Every attempt (refused or applied, and at which stage) is logged to
  `/var/log/baseline/vm_scripts.events.jsonl` - the same durable,
  count-preserving discipline `tools/bounded_log.py` establishes
  elsewhere, so a repeated refused/failed attempt is a real, visible
  signal rather than silent noise.

## Verification performed before this commit

- RED confirmed first: `ModuleNotFoundError: No module named
  'vm_scripts'` before any implementation existed.
- 13 new unit tests (`tests/unit/test_vm_scripts.py`), all passing,
  using the existing `tests/unit/fake_runner.FakeRunner` - no new fake
  infrastructure needed. Covers: unknown-script refusal without
  fetching, hash-match/mismatch for both the entry script and
  `core/build.func`, fetch-failure refusal, refusal-before-execution in
  both failure modes, the verified-content-plus-override-env execution
  path, and exactly-one-event-per-attempt logging.
- Full suite: 894/894 passing (868 before this pair of changes; this
  record's 13 tests plus record 58's 13 account for the difference),
  no regressions. (Record 59 later found two real bugs neither this
  record's nor record 58's fake-based tests caught, and added more
  tests fixing that - see record 59 for the current total.)
- Manifest hashes independently re-verified against the real, live
  upstream files during this session (shown in this record's own
  evidence above) - not asserted from memory.
- **Not verified**: no real `curl` fetch, no real `bash -c` execution,
  no real `pct create`/`qm create` has been run by this code against a
  real Proxmox host in this pass.
