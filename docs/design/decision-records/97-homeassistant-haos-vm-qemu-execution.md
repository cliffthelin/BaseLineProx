# Decision record: `homeassistant-lxc` and `haos-vm` executed under real QEMU - the last 2 of 6 curated Helper-Scripts

Status: **both executed for real under a fresh disposable QEMU VM each
(same discipline as decision records 59/61). No product code changed -
this closes v0.1 work-queue item 18 and v0.2 work-queue item 16, purely
by gathering the missing real evidence `vm_scripts.py`'s own docstring
already said was outstanding.**

## What this resolves

v0.2 work-queue item 16 ("Run `homeassistant-lxc` and `haos-vm` under
real QEMU"), unblocked (empty "Blocked on" column) and next in order per
the queue's own "first `[ ]` item whose Blocked on column is empty"
rule. Also closes v0.1 work-queue item 18 (the same ask, carried
forward from that queue) and upgrades v0.1 item 15 from `[~]` (partial)
to `[x]` - all 6 curated `SCRIPT_MANIFEST` entries are now directly
observed at least once.

## What was done

Reproduced records 59/61's exact disposable-QEMU-smoke-test discipline:
Debian 13 (trixie) generic-cloud qcow2 base image, a fresh writable
qcow2 overlay per script (base image never written to), a NoCloud
cloud-init seed embedding the real repo files needed to import
`vm_scripts.py` and call `run_script()` against a real
`repair.RealRunner` - real curl fetches, real hash verification, real
`bash -c` execution of the actual pinned upstream script content, no
mocking.

**One real gap found in the test harness itself (not a product bug):**
the file list this kind of smoke test embeds into the guest
(`repair.py`, `vm_scripts.py`, `ifnet_config.py`, `network.py`,
`topology.py`, `pct_provision.py`, `vm_provision.py`) predates decision
record 89's `registry.py` - `network.py` now imports it
(`baseline/lib/network.py:23`) as part of the settings-to-SQL
migration work, so the first attempt at both VMs failed identically:
`ModuleNotFoundError: No module named 'registry'`, confirmed directly
via `virt-cat`... actually via a passwordless-sudo-mounted read-only
loop mount of the powered-off guest's own root filesystem (`/var/log/
baseline_driver.log`), since `libguestfs`/`virt-cat` couldn't build its
appliance in this sandboxed session (`/boot/vmlinuz-*` not readable by
this user - a sandbox limitation, not fixed). Added `registry.py`
(stdlib-only: `json`/`os`/`sqlite3`/`time`, no further transitive
dependency) to the embedded file list and re-ran both VMs fresh from
clean overlays. This is a real, disclosed instance of "this project's
own codebase moved since the smoke-test discipline was last exercised" -
worth remembering for the *next* time this pattern is reused, not
specific to these two scripts.

## Real results (second, corrected run)

- **`homeassistant-lxc`** (`ct/homeassistant.sh`) - `outcome: applied`,
  exit 0, completed in ~2s after cloud-init's own 'finished' timestamp.
  stdout was only `core/build.func`'s own header banner, printed twice,
  with no visible `apt`/install activity - a **third**, previously
  unobserved real outcome under the same "no interactive terminal"
  condition that produced `debian-lxc`'s real mutation and
  `docker-lxc`'s real refusal. Read honestly: "reported success without
  visible mutation in captured stdout," not "definitely did nothing" -
  `run_script()` only captures stdout on success and this project has
  not traced upstream's internal branch logic to confirm no side effect
  occurred silently. Does not generalize from `debian-lxc`/`docker-lxc` -
  a third LXC-kind script, a third real behavior.
- **`haos-vm`** (`vm/haos-vm.sh`) - `outcome: refused`, exit 127,
  `pveversion: command not found`, failed in under 1s. Confirms the
  VM-kind pattern `debian-vm` (record 61) already showed is not
  specific to that one script - both VM-kind entries checked so far
  hard-require `pveversion` and fail closed immediately without it,
  with no update-in-place fallback of the kind LXC-kind scripts have.

## Files changed

- `baseline/lib/vm_scripts.py` - module docstring's real-evidence
  section rewritten from "four real data points... homeassistant-lxc
  and haos-vm are fetch+hash-verified but not yet executed" to six,
  with `homeassistant-lxc`'s own distinct third-outcome case stated
  explicitly rather than folded into `debian-lxc`'s.
- No other product file changed - this record is evidence-gathering
  only, not a code fix.

## Verification performed

- Full suite re-run after the docstring edit: 1465/1465 (unchanged
  from before this record - no behavioral code changed).
- Both scripts' real outcomes captured verbatim from the guest's own
  `/var/log/baseline_driver.log` (first, failed attempt) and the host-
  side `RESULT_JSON` line written to a dedicated second serial port
  (second, corrected attempt) - not paraphrased, not assumed.
- Disposable QEMU VMs, their qcow2 overlays, the downloaded base cloud
  image, and the NoCloud seed ISOs all deleted after this record was
  written - matches this project's established disposable-QEMU-proof
  retention discipline. Raw result/console logs kept only at
  `/tmp/v02-item16-results/` (outside the repo, this session's own
  scratch area) for reference while writing this record.

## What remains open (unrelated to this record, tracked separately)

Everything else already listed as open in `v0.2-work-queue.md` items
20-22 (Quadlet `.network` units, an API/MCP orchestration layer,
persistence wiring for container volumes) - untouched by this record.
