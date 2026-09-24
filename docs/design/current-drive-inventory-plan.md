# Design for review v2: current-drive inventory manifest

**Status: implementation milestone accepted; a controlled first run on
the current drive is authorized, subject to a final code review through
a separate draft PR.** v1 was approved in direction 2026-09-20 with nine
revisions (this document, below); v2 got ten further corrections
(round 3, implemented); Cliff then accepted that implementation based on
the reported 54/54 test results (not a direct line-by-line review — he
has no GitHub access from his environment) and added two more fail-closed
corrections plus a required pre-run validator (round 4, also implemented,
now 74/74). The collector, its unit tests, and the validator live at
`baseline/lib/inventory/` on this branch
(`inventory/current-drive-manifest`, off `main`), opened as its own draft
PR, separate from PR #1 (`repair/host-network-reset-to-dhcp`) and from the
[Proxmox read-only diagnostics plan](proxmox-readonly-diagnostics-plan.md).
**Still not run against the current drive or a real host by this
session** — the first run is Cliff's (or a physically/VM-connected
session's) to perform, following the first-run procedure at the end of
this document. See "Corrections applied in implementation" and
"Round 4: fail-closed allowlists and the pre-run validator" immediately
below for what changed and why, and
`current-drive-inventory-example-manifest.json` (same directory) for a
generated example built entirely from synthetic data.

## Corrections applied in implementation (round 3)

Ten corrections, each addressed in code, not just prose. Referenced by
number against Cliff's own list:

1. **Tools manifest is five tools only** — `baseline/lib/inventory/tools_manifest.json`
   now has exactly `lm-sensors`/`nvme-cli`/`smartmontools`/`iperf3`/`ethtool`.
   NUT and ProxMenux are recorded under "Explicitly deferred" in the table
   below, not probed by `collectors/tools.py` at all — the ordinary package
   inventory (`collectors/system.py`) still surfaces NUT packages if
   installed.
2. **No cross-branch dependency** — `baseline/lib/inventory/runner.py` is a
   local `Runner`/`RealRunner`, not an import of `repair.Runner` (which
   only exists on `repair/host-network-reset-to-dhcp`, a branch this one
   doesn't descend from). A shared runner is future work for after both
   branches merge into `main`, not before.
3. **`pvesubscription get` removed entirely** — `collectors/proxmox.py::collect_repo_and_subscription()`
   never calls it. It reads only whether the enterprise/no-subscription
   APT sources are enabled and records `subscription_status: "unavailable"`
   with an explicit reason until a real host confirms a safe,
   field-specific query exists.
4. **`datacenter.cfg` uses a reviewed key allowlist**, same as
   `storage.cfg` — unknown fields are recorded as names/counts only, never
   values (`collectors/proxmox.py::collect_datacenter_cfg()`). Node names
   are HMAC-tokenized (`"host:..."`), VMIDs are tokenized consistently
   within one run (`"vmid:..."`), and `/var/spool/cron/crontabs` other-user
   entries are recorded as a count plus tokenized identities, never raw
   usernames (`collectors/scheduling.py`).
5. **"Never read" → "never retained in normalized output."** `dmidecode`'s
   raw text is parsed against an explicit key allowlist and goes out of
   scope inside the same function (`collectors/system.py::collect_firmware_drivers()`)
   - nothing raw is logged, included in an exception, or written to a
   temp file anywhere in this module.
6. **Deterministic testing fixed** — `Redactor`'s HMAC key and
   `collect_all()`'s clock are both injectable (`baseline/lib/inventory/redact.py`,
   `manifest.py`). Tests prove all three properties: fixed key + fixed
   clock → byte-identical output; default (ephemeral) key → different
   tokens across two production-style runs; same key within one run →
   stable repeated tokens (`tests/unit/inventory_tests/test_manifest.py`).
7. **Every command is bounded** — `runner.py`'s `run()` takes an explicit
   timeout and max-output-size and returns `timed_out`/`output_truncated`/
   `permission_denied`/`unavailable` states rather than raising;
   `walk_bounded()` replaces the unbounded `ls -laR` with an explicit max
   depth and entry count; `${Conffiles}` is queried for every package in
   one batched `dpkg-query` pass; binary detection uses `shutil.which()`,
   never a shelled-out `command -v`.
8. **`pvesm status` reconciled with the volatile-data exclusion** —
   `collect_pvesm_status()` keeps name (tokenized), type, enabled state,
   and total capacity; live used/available/percent columns are dropped.
   Shared state and content types come from `storage.cfg`, not duplicated
   here.
9. **Output-path protection tightened** — `pathsafety.py` resolves the
   full requested path (which also resolves every existing symlinked
   parent and collapses `..` traversal in the same call) before checking
   forbidden roots, and `atomic_write()` independently re-validates
   immediately before writing rather than trusting an earlier check -
   noted in the module docstring as best-effort within what pure Python
   can guarantee, not a full TOCTOU close. Tests cover symlinked parents,
   `..` traversal, and a symlink appearing at the final path.
10. **`/etc/pve/nodes/<node>/priv/` invariant corrected** — the test
    (`test_never_lists_or_reads_priv_directory`) now asserts the collector
    never calls `listdir`/`read_text` on any path containing `priv` at
    all, rather than asserting it handles a `PermissionError` gracefully
    - matching Cliff's point that receiving that error would already mean
    the allowlist boundary had been violated.

**Test results:** `54 passed` (`pytest tests/unit -v`), all against a
local `FakeRunner` (`tests/unit/inventory_tests/fake_runner.py`) - no real
subprocess, filesystem, or network access anywhere in the suite.

## Round 4: fail-closed allowlists and the pre-run validator

Cliff accepted the round-3 implementation from the test report alone and
added two more corrections plus a required safeguard before authorizing
a first run on the real drive:

- **`datacenter.cfg` unknown keys** — already fail-closed as built:
  `collect_datacenter_cfg()` only ever puts allowlisted keys' *values*
  into `fields`; unknown keys go into `unknown_fields.names` (a list of
  key names) and `unknown_fields.count`, never a value. No code change
  was needed here — `test_datacenter_cfg_unknown_fields_recorded_as_names_only_no_values`
  already covered it.
- **Sysctl discovered-vs-reviewed split** — `collect_sysctl()` now
  returns `discovered_keys` (every key found in `/etc/sysctl.conf` and
  `/etc/sysctl.d/*.conf`, by name only) separately from `values` (which
  only ever contains keys from the small, separately reviewed
  `SYSCTL_ALLOWLIST`). A key merely appearing in a config file no longer
  earns it a live `sysctl <key>` query on its own — previously the union
  of discovered and allowlisted keys was queried, which meant an
  unreviewed key from a config file got its live value read. Three new
  tests in `test_security.py` cover: discovered-but-not-queried,
  reviewed-and-queried, and a key that's both.
- **Every collector now reports why a field is empty, not just that it
  is** — this was the real gap behind Cliff's "every unavailable, timed
  out, truncated, or denied category is visibly reported" requirement.
  Before round 4, most collectors (everything outside `proxmox.py`'s
  `storage_cfg`/`datacenter_cfg`/`pvesm_status` and `tools.py`) silently
  fell back to `None`/`[]`/`{}` on any command failure, indistinguishable
  from "genuinely nothing there." Every collector function now returns an
  additional `"_collection_notes"` list (via the new
  `collectors/status_notes.py` helper) recording, for every failed
  command/read/listdir call, its label and one of
  `timed_out`/`permission_denied`/`unavailable`/`error`/`output_truncated`
  plus the underlying reason. An empty list means everything that
  collector attempted succeeded cleanly.
- **`baseline/lib/inventory/validate.py`** (new) — the required pre-run
  safeguard, wired up as `baseline-drive-inventory validate --manifest
  <path>`. It only reads; it never writes anything, including to the
  manifest it checks (`test_validator_never_writes_anything`). Five
  checks, four of them hard pass/fail and one advisory:
  1. `schema_validity` — required top-level keys present,
     `schema_version` matches this codebase's.
  2. `output_permissions` — the manifest file on disk is mode `0600`,
     nothing looser.
  3. `forbidden_field_names` — no key anywhere in the manifest looks like
     a raw secret field (`password`/`secret`/`apitoken`/`keyring`/
     `encryption`/`cipassword`/`privkey`), except the small set of
     `_token`-suffixed keys this tool itself emits as redaction-token
     field names (`vmid_token`, `name_token`) - those hold HMAC tokens,
     not secrets.
  4. `secret_value_patterns` — no string value anywhere matches a raw
     IPv4/IPv6 address, MAC address, UUID, an embedded URL credential
     (`://user:pass@`), a private-key marker, SSH key material, or a
     Proxmox-subscription-key shape.
  5. `large_text_values_for_manual_review` (advisory, doesn't fail the
     run) — flags any single string value over 4000 characters as
     possible retained raw output, for a human to look at directly.

  A separate, non-pass/fail pass, `collect_degraded_categories()`, walks
  the manifest and surfaces every `available: false`, `timed_out: true`,
  `output_truncated: true`, `permission_denied: true`,
  `subscription_status: "unavailable"`, and non-empty
  `_collection_notes` list it finds, by field path, so a human reviewer
  sees the whole list in one place. Run against the regenerated synthetic
  example manifest, it passes all four hard checks and honestly reports
  nine degraded categories (the five diagnostic tools not present in the
  synthetic environment, one `efibootmgr` note, the always-unavailable
  subscription status, and two `_collection_notes` entries) — proving the
  validator can actually see collector-reported gaps, not just that it
  runs.

  **This validator is defense in depth, not upload authorization** —
  passing it doesn't mean the manifest is safe to share; a human still
  reviews it directly first, per the first-run procedure below.

**Test results after round 4:** `74 passed` (`pytest tests/unit -v`) — the
original 54, plus 4 new sysctl/firewall tests in `test_security.py` and
16 new validator tests in `test_validate.py`.

## Why this exists

Before the boot-time recovery service from
[the reset-interface-to-dhcp plan](reset-interface-to-dhcp-plan.md) is
designed and installed, Cliff wants two independent, comparable pictures of
a real host: **the current BaselineOS physical drive**, frozen before any
integration-related modification, and **a disposable Proxmox VM**, built
and tested from scratch. Comparing the two surfaces what the current drive
has that a fresh build wouldn't (drift, one-off fixes, leftover state) and
what a fresh build needs that the drive's own history might not show.

**The single most important addition in this revision is `/etc/pve`.**
Without Proxmox's own managed configuration — storage definitions, node
config, firewall rules, cluster/subscription state — a disposable VM could
faithfully reproduce Debian and the Baseline application and still be
missing storage, networking, or guest definitions the real deployment
depends on. `/etc/pve` is also a live `pmxcfs` filesystem, not an ordinary
directory, so it's handled field-by-field below, never recursively copied.

This stays a **separate, broader** tool from
`boot/baseline-repair-env-probe.sh` (which only answers the narrow
boot-ordering question). They may share primitives (redaction helpers, the
`run()`/`section()` pattern) but remain separate scripts, and this tool
still does not go into PR #1.

## Scope: what the manifest records

| Category | What it captures |
|---|---|
| Packages | Installed packages + versions, held packages, architecture (multi-arch) |
| APT | Legacy + Deb822 sources, pins, holds, policy output |
| Platform versions | Kernel, Proxmox VE, Debian versions |
| Firmware/drivers | Kernel modules, hardware-to-driver bindings (`lspci -nnk`), BIOS summary (allowlisted fields only) |
| systemd | Enabled/active units, overrides, locally-modified units (`systemd-delta`) |
| Network | `/etc/network/interfaces` closure, DNS resolver config |
| Storage | Mounts, block devices, filesystem types, LVM/ZFS if present |
| Boot | Bootloader config, kernel command line, `proxmox-boot-tool status`, EFI presence (allowlisted fields only) |
| Kernel modules/udev | `modules-load.d`, `modprobe.d`, udev rules |
| Firewall/sysctl/DNS/time | Ruleset summary, intentional sysctl keys, DNS, NTP/timezone, journald config/persistence |
| Runtimes | Interpreter versions Baseline itself needs |
| Scheduling | System cron, `/etc/crontab`, root + allowlisted crontabs, systemd timers |
| Baseline configuration | `/etc/baseline/*` structure, `/var/lib/baseline/*` layout, service state |
| **Proxmox-managed configuration** | **New.** `storage.cfg`, `datacenter.cfg`, node config, VM/CT config presence + non-secret structural fields, Proxmox firewall, `pvesm status`, cluster membership, repo/subscription state |
| Diagnostic tools | Presence + version of each of the five tools below |

## 1. The five-tool manifest

**Corrected in round 3: exactly five tools, not seven.** NUT and
ProxMenux were in an earlier round's table; Cliff's follow-up correction
removed them from this list entirely - not as a gap waiting to be filled,
but as a deliberate scope decision:

- **Network UPS Tools (NUT)** — deferred because this machine has no UPS
  attached. The ordinary package inventory (`collectors/system.py`)
  already shows NUT packages if they happen to exist; no special service
  inspection is needed for that.
- **ProxMenux** — deferred until it is intentionally evaluated, consistent
  with [the diagnostics plan's](proxmox-readonly-diagnostics-plan.md) own
  deferral of it. Not probed here at all.

Kept as an **external, versioned** file
(`baseline/lib/inventory/tools_manifest.json`, shown in full below)
precisely because this list can grow without touching the collector's
code — `collectors/tools.py` reads it and iterates, it never hardcodes a
tool name.

| Tool | Debian package | Primary detection |
|---|---|---|
| lm-sensors | `lm-sensors` | `sensors -v`; package version |
| nvme-cli | `nvme-cli` | `nvme version`; package version |
| smartmontools | `smartmontools` | `smartctl --version`; package version |
| iperf3 | `iperf3` | `iperf3 --version`; package version |
| ethtool | `ethtool` | `ethtool --version`; package version |

Every detection command is a version query, checked via `shutil.which()`
for binary presence (never a shelled-out `command -v` — design doc
correction #7) — nothing here starts a service, opens a listener,
launches an interactive menu, or runs a hardware test.

```json
{
  "schema_version": 2,
  "tools": [
    {
      "name": "lm-sensors",
      "debian_package": "lm-sensors",
      "detect": {"binary": "sensors", "version_command": ["sensors", "-v"]},
      "package_version_command": ["dpkg-query", "-W", "-f=${Version}", "lm-sensors"]
    },
    {
      "name": "nvme-cli",
      "debian_package": "nvme-cli",
      "detect": {"binary": "nvme", "version_command": ["nvme", "version"]},
      "package_version_command": ["dpkg-query", "-W", "-f=${Version}", "nvme-cli"]
    },
    {
      "name": "smartmontools",
      "debian_package": "smartmontools",
      "detect": {"binary": "smartctl", "version_command": ["smartctl", "--version"]},
      "package_version_command": ["dpkg-query", "-W", "-f=${Version}", "smartmontools"]
    },
    {
      "name": "iperf3",
      "debian_package": "iperf3",
      "detect": {"binary": "iperf3", "version_command": ["iperf3", "--version"]},
      "package_version_command": ["dpkg-query", "-W", "-f=${Version}", "iperf3"]
    },
    {
      "name": "ethtool",
      "debian_package": "ethtool",
      "detect": {"binary": "ethtool", "version_command": ["ethtool", "--version"]},
      "package_version_command": ["dpkg-query", "-W", "-f=${Version}", "ethtool"]
    }
  ]
}
```

This is the exact, current contents of `baseline/lib/inventory/tools_manifest.json`.

## 2. Proxmox-managed configuration (new)

`/etc/pve` is `pmxcfs`, a FUSE filesystem backed by a SQLite-based
distributed config store, not a directory of ordinary files — the tool
**never** walks it recursively or treats it like `/etc`. Every read below
is an explicit, named path or command, each with its own field-level
allowlist:

- **`/etc/pve/storage.cfg`** — parsed per storage block. Kept:
  `type`, `content`, `nodes`, `shared`, `maxfiles`, and similar structural
  keys. Redacted/dropped by key name, not by guessing: `password`,
  `encryption-key`, `keyring`, any key containing `secret`/`token`/`key`
  (case-insensitive) — a storage backend's `username` is kept (not secret
  by itself; needed to know the storage is configured at all), its
  `password` is not.
- **`/etc/pve/datacenter.cfg`** — read whole; this file is cluster-wide
  behavior settings (migration, HA, console defaults, keyboard layout,
  MOTD, etc.), not identity or secret material, so it's kept structurally
  as-is once confirmed against a real file's key set (not invented here —
  flagged below).
- **Node configuration under `/etc/pve/nodes/`** — **not** walked
  recursively. Only `/etc/pve/nodes/<node>/qemu-server/*.conf` and
  `/etc/pve/nodes/<node>/lxc/*.conf` are enumerated (by VMID, presence
  only) and each parsed for a **fixed allowlist** of structural fields
  (`cores`, `memory`, `net0..N`'s bridge/model — never a MAC unless
  redacted, `bootdisk`, `ostype`, `scsihw`) — never `cipassword`,
  `sshkeys`, `cicustom`, or any cloud-init secret field, never the full
  raw config blindly. Anything under `/etc/pve/nodes/<node>/priv/` (host
  keys, PVE's own TLS private material) is never read at all.
- **Proxmox firewall** — `/etc/pve/firewall/cluster.fw`,
  `/etc/pve/nodes/<node>/host.fw`, and per-VM `/etc/pve/firewall/<vmid>.fw`
  if present. Rule structure (`action`, `proto`, `dport`/`sport`, `iface`)
  is kept; `source`/`dest` IP/CIDR values are redacted through the same
  HMAC tokenization as other addresses (see Redaction below).
- **`pvesm status`** — command output, storage availability/type/size
  summary; no credentials appear in this output by design.
- **Cluster membership/status** — reuses `repair.py::check_standalone_host()`'s
  own corosync-file-existence check rather than adding a second way to
  answer the same question; if clustered, `pvecm status`'s membership list
  is recorded with node names kept (operationally meaningful) and no IP
  addresses unredacted.
- **Proxmox repository and subscription configuration** —
  `/etc/apt/sources.list.d/pve-enterprise.list` /
  `pve-no-subscription.list` (which repo channel is configured — not
  normally credential-bearing, but scanned by the same APT-credential-URL
  redaction as every other APT source, below) and `pvesubscription get`
  filtered to **status only** (`NotFound`/`New`/`Active`/`Invalid` and
  expiry, never the subscription key itself).

**Explicitly never collected from `/etc/pve`:** any VM/CT config field not
on the allowlist above, cloud-init secrets, SSH keys embedded in any VM
config, TLS private keys, join/cluster secrets, and the subscription key.

**Flagged for confirmation, not invented:** the exact key sets above are
built from well-known Proxmox config semantics, but this session has no
real Proxmox host to validate the allowlists against actual file contents
— same limitation as the boot-recovery-service ordering question. The
allowlists should be spot-checked against a real `/etc/pve` (Cliff's own,
or the disposable VM) before the collector is finalized, not just before
it's run.

## 3. Completed platform inputs

Added to the command list below: Deb822 `sources.list.d/*.sources`,
`apt-cache policy`, `dpkg --print-architecture` + foreign architectures,
per-package `${Conffiles}` metadata (conffile-modified detection),
`systemd-delta` (overrides/locally-modified units, replacing the narrower
"find override.conf" approach), `lspci -nnk` (driver bindings),
`/etc/sysctl.conf` alongside `/etc/sysctl.d/`, `/etc/default/grub` +
`/etc/kernel/cmdline` + `proxmox-boot-tool status`, and journald
configuration/persistence mode (not log contents). Structured output
(`-j`/`-o json`/explicit `--showformat`) is used everywhere the tool
supports it, so the collector parses JSON rather than localized
human-readable text wherever possible.

## Complete list of read-only commands (v2)

```
dpkg-query -W -f='${Package}\t${Version}\t${Status}\n'
apt-mark showhold
dpkg --print-architecture
dpkg --print-foreign-architectures
cat /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources
cat /etc/apt/preferences.d/* (if present)
apt-cache policy
dpkg-query -W -f='${Conffiles}\n' <package>   (per package, for conffile-modified detection)
uname -a
pveversion -v
cat /etc/debian_version /etc/os-release
lsmod
lspci -nnk
dmidecode -t bios -t system   (parsed, allowlisted keys only - see Redaction)
systemctl list-units --type=service --all
systemctl list-unit-files
systemd-delta
systemctl cat <unit>   (only for units systemd-delta flags as overridden/extended)
cat /etc/network/interfaces + interfaces.d/* (reused, same redaction as the probe script)
resolvectl status  /  cat /etc/resolv.conf
findmnt -D
lsblk -f
vgs / lvs / zpool list   (only if lvm2/zfsutils are installed; skipped otherwise)
efibootmgr   (presence + entry count only - see Redaction, no -v)
cat /proc/cmdline
cat /etc/default/grub
cat /etc/kernel/cmdline (if present)
proxmox-boot-tool status   (if present - Proxmox's own boot-management path)
ls /etc/modules-load.d/ /etc/modprobe.d/ /etc/udev/rules.d/
nft list ruleset  /  iptables-save   (whichever is active; neither is invoked if absent)
cat /etc/sysctl.conf /etc/sysctl.d/*.conf
sysctl <exact key>   (one per intentional key found above, plus a small reviewed allowlist - see Sysctl handling)
resolvectl status  (DNS)
timedatectl status
journalctl --disk-usage ; cat /etc/systemd/journald.conf /etc/systemd/journald.conf.d/*.conf   (config/persistence only, never log bodies)
systemctl list-timers --all
cat /etc/crontab ; ls /etc/cron.d /etc/cron.daily /etc/cron.hourly /etc/cron.weekly /etc/cron.monthly
crontab -l -u root ; crontab -l -u baseline   (root + explicitly allowlisted service accounts only)
ls /var/spool/cron/crontabs/   (presence of other users' crontabs, contents not read unless separately approved)
python3 --version ; node --version (if present) ; other interpreters actually referenced by Baseline
ls -la /etc/baseline/
cat /etc/baseline/*.json (values redacted per rules below)
ls -laR /var/lib/baseline/
systemctl status baseline.service --no-pager
cat /etc/pve/storage.cfg /etc/pve/datacenter.cfg   (parsed, allowlisted keys only)
ls /etc/pve/nodes/<node>/qemu-server/ /etc/pve/nodes/<node>/lxc/   (presence only)
cat /etc/pve/nodes/<node>/qemu-server/<vmid>.conf /etc/pve/nodes/<node>/lxc/<vmid>.conf   (allowlisted keys only)
cat /etc/pve/firewall/cluster.fw /etc/pve/nodes/<node>/host.fw /etc/pve/firewall/<vmid>.fw   (if present, redacted addresses)
pvesm status
pvecm status   (only if clustered, per the existing corosync check)
pvesubscription get   (status/expiry fields only)
for each tool in tools_manifest.json: its own detect.version_command and package_version_command
```

## Manifest schema (v2)

Same per-run JSON shape as v1, with a `proxmox` category added:

```json
{
  "schema_version": 2,
  "generated_at": "2026-09-20T22:00:00Z",
  "source": "current-drive | disposable-vm",
  "host_label": "<Cliff-assigned free-text label, never a hostname/serial>",
  "categories": {
    "packages": { "items": [...], "architecture": "...", "foreign_architectures": [...] },
    "apt": { "sources": [...], "deb822_sources": [...], "pins": [...], "holds": [...], "policy_summary": {...} },
    "platform_versions": { "kernel": "...", "proxmox": "...", "debian": "..." },
    "firmware_drivers": { "modules": [...], "pci_driver_bindings": [...], "bios_summary": {"vendor": "...", "version": "...", "release_date": "...", "system_manufacturer": "...", "system_product": "..."} },
    "systemd": { "enabled_units": [...], "overridden_units": [...], "systemd_delta_findings": [...] },
    "network": { "interfaces_closure": "<redacted>", "dns": {...} },
    "storage": { "mounts": [...], "block_devices": [...] },
    "boot": { "bootloader": "...", "kernel_cmdline": "<redacted>", "efi_present": true, "efi_boot_entry_count": 3, "proxmox_boot_tool_status": "..." },
    "kernel_modules_udev": {...},
    "firewall_sysctl_dns_time": { "ruleset_summary": "<redacted>", "sysctl_set": {...}, "dns": "...", "time": {...}, "journald": {...} },
    "runtimes": {...},
    "scheduling": { "system_cron": [...], "etc_crontab": "<sanitized>", "root_crontab": "<sanitized>", "allowlisted_service_crontabs": {...}, "systemd_timers": [...], "other_user_crontabs_present": ["userA", "userB"] },
    "baseline_config": {...},
    "proxmox": {
      "storage_cfg": {...},
      "datacenter_cfg": {...},
      "nodes": { "<node>": { "vm_ct_configs": [ {"vmid": "...", "type": "qemu|lxc", "fields": {...}} ] } },
      "firewall": {...},
      "storage_status": {...},
      "cluster": {"clustered": false, "membership": null},
      "repo_and_subscription": {"channel": "no-subscription", "subscription_status": "NotFound"}
    },
    "diagnostic_tools": { "<tool-name>": {"present": true, "version": "...", "package_version": "..."} }
  },
  "config_files": [ /* per-file drift-evidence records, see below */ ],
  "redaction_report": { "fields_redacted": 0, "categories_with_redactions": [] }
}
```

## Diff/classification schema (new — addresses "do not auto-declare")

**Not yet implemented.** There is only one manifest-producing tool on
this branch (`baseline/lib/inventory/`); `diff.py` and the classification
step below are deferred until both a real current-drive manifest and a
disposable-VM manifest exist to compare — this section stays as the
target design for that later work, not a description of anything built
so far.

The single-run manifest above never classifies anything as required or
obsolete — that only happens when two manifests are diffed, and even then
the tool's own output is a **suggestion**, never authoritative. One record
per differing field:

```json
{
  "field_path": "categories.systemd.enabled_units[+]:foo.service",
  "current_drive_value": "enabled",
  "disposable_vm_value": null,
  "tool_suggestion": "candidate_obsolete",
  "evidence": "not referenced in any collected config, no systemd override, not part of tools_manifest.json",
  "classification": {
    "status": "unknown",
    "rationale": null,
    "reviewer": null,
    "review_timestamp": null
  }
}
```

`tool_suggestion` is one of `suggested_required`, `suggested_machine_specific`,
`detected_secret_identity`, `candidate_obsolete`, `unknown` — matching
Cliff's five labels exactly, always prefixed "suggested"/"candidate"/
"detected" to make clear the tool is proposing, not deciding.
`classification.status` starts at `unknown` for **every** field regardless
of `tool_suggestion` and is the only field a later review step is allowed
to overwrite (to `confirmed_required` / `confirmed_machine_specific` /
`confirmed_secret_identity` / `confirmed_obsolete`) — with `rationale`,
`reviewer`, and `review_timestamp` filled in at that time. A difference
with no clear tool suggestion defaults to `unknown` on both axes, never
guessed into a more specific bucket.

## Redaction rules (v2)

**HMAC-based tokenization, not plain hashing.** In production, a fresh
random key (`os.urandom(32)`, `Redactor`'s default in
`baseline/lib/inventory/redact.py`) is generated at the start of each run,
held only in process memory, and discarded when the run ends — never
written to disk, never included in the manifest. As built, that key is
injectable: tests pass a fixed key to get byte-identical output across
runs, while a real CLI invocation always gets a fresh ephemeral one, so
two independent production runs never produce matching tokens (design doc
correction #6). Every identity/machine-specific value is redacted to
`HMAC-SHA256(key, "<kind>:<value>")[:12]`, prefixed by type (`ip:...`,
`mac:...`, `host:...`, `uuid:...`). This is deliberately **not** a plain
hash: IPv4 addresses, MACs, and hostnames are low-entropy enough that a
plain hash can be reversed by enumeration (hash every possible value,
compare) — an HMAC with a secret, never-persisted key closes that off.
Tokens stay consistent *within* one manifest (so structural comparisons
still work — the same address maps to the same token twice) and are never
comparable *across* manifests or runs, since each run's key is thrown
away.

- **Never retained in normalized output:** private keys, TLS
  private-key halves, `/etc/baseline/harness.env` values (names only),
  TPM/LUKS key material, `/etc/pve/nodes/<node>/priv/*`, VM/CT cloud-init
  secret fields, any subscription key, any file matched by a
  `.gitignore`-style secrets-exclusion list shipped with this tool. Per
  correction #5, this is stronger than "never read": where a command's
  raw output can't be avoided (e.g. `dmidecode`, `storage.cfg`), the raw
  text is parsed for allowlisted fields only and discarded in the same
  function — never logged, never included in an exception message, never
  written to a temporary file, and never held past that parsing step.
- **Structure-only, values redacted:** `/etc/network/interfaces`,
  `/etc/baseline/*.json`, SSH `known_hosts`/`authorized_keys` (count + key
  type only), `/etc/pve/storage.cfg` (per the key-name rule above).
- **Identity/machine-specific, HMAC-tokenized as above:** hostname,
  machine-id, MAC addresses, IP addresses, disk serials/UUIDs, **firewall
  rule source/dest addresses**, **mount `SOURCE` device paths and
  filesystem labels** (device paths and labels can be as identifying as a
  serial number), **kernel command line** (scanned for
  `root=UUID=...`/similar identity-bearing arguments and tokenized
  per-argument, structure kept), **cron command arguments** (any argument
  matching a URL, path, or token-shaped value is tokenized; the command
  name itself is kept).
- **Credential-bearing URLs:** any APT source or Proxmox repo URL
  containing embedded `user:pass@` credentials has the credential portion
  stripped entirely (not tokenized — dropped), keeping only the host/path
  structure.
- **`dmidecode`/`efibootmgr`, allowlist-only (not raw-then-redact):**
  `dmidecode` output is parsed line-by-line and only these keys are ever
  kept: BIOS Vendor, BIOS Version, BIOS Release Date, System Manufacturer,
  System Product Name. Every other key (serial numbers, UUIDs, asset
  tags, chassis identifiers, anything else) is never even read into the
  intermediate structure, let alone redacted after the fact. `efibootmgr`
  is run without `-v` and only `boot_entry_count` and `efi_present` are
  recorded — no entry names, no device paths.
- **Kept as-is:** package names/versions, unit names, mount points and
  filesystem *types* (not sources/labels), kernel module names, sysctl
  key names, interface names/stanza types, tool presence/versions, node
  names in cluster membership, Proxmox storage `type`/`content`/`shared`.

Anything not explicitly covered above is **redact by default** until
reviewed.

## Configuration-drift evidence (new)

Every collected config file gets one record in `config_files`, not just
its content:

```json
{
  "path": "/etc/network/interfaces",
  "owning_package": "ifupdown2",
  "file_type": "config",
  "owner": "root", "group": "root", "mode": "0644",
  "sanitized_content": "<redacted text, only for allowlisted files>",
  "hash_sha256": "8f3a...",
  "conffile_modified": true
}
```

`owning_package` comes from `dpkg -S <path>` (null if unowned/untracked).
`conffile_modified` comes from comparing the package's recorded conffile
hash (from `${Conffiles}` metadata) against the file's current hash — a
package-level fact, independent of this tool's own redaction.
**`hash_sha256` is omitted entirely** whenever the file's content includes
any secret/identity material this tool would otherwise redact — a hash of
excluded content can still leak information (confirms a guessed value,
enables correlation across manifests) even though the content itself
isn't shown, so a hash is only ever computed for files the tool is willing
to show in full.

## Paths examined (v2)

```
/etc/apt/                     (sources, preferences, .sources)
/etc/network/                 (interfaces + interfaces.d/*)
/etc/systemd/system/          (via systemd-delta, not a raw find)
/etc/modules-load.d/  /etc/modprobe.d/  /etc/udev/rules.d/
/etc/sysctl.conf  /etc/sysctl.d/
/etc/cron.d/  /etc/cron.daily/ /etc/cron.hourly/ /etc/cron.weekly/ /etc/cron.monthly/
/etc/crontab
/var/spool/cron/crontabs/     (listing only, except root + allowlisted accounts)
/etc/baseline/
/var/lib/baseline/            (layout/listing only; contents only where explicitly allowlisted)
/etc/default/grub  /etc/kernel/cmdline
/etc/systemd/journald.conf  /etc/systemd/journald.conf.d/
/proc/cmdline
/etc/pve/storage.cfg  /etc/pve/datacenter.cfg
/etc/pve/nodes/<node>/qemu-server/*.conf  /etc/pve/nodes/<node>/lxc/*.conf  (allowlisted fields only, never recursive)
/etc/pve/firewall/
```

Nothing outside these paths (plus the command outputs listed above) is
read. No home directories, no `/root`, no `/etc/pve/nodes/<node>/priv/`,
no application data directories other than Baseline's and Proxmox's own
managed config, are examined.

## Exclusions for volatile/runtime data

Unchanged from v1 — still out of scope: live process list, live
connections/sockets/ARP, log *contents*, live DHCP/IP state, uptime/current
time value, disk free-space percentages, `/tmp`, `/var/tmp`, `/run`.

## Comparison categories (v2 wording)

Cliff's correction: absence from the repository doesn't prove something is
obsolete — it could be an undocumented requirement. Every difference the
tool finds is *always* produced as a **suggestion**, using exactly these
five labels (see Diff/classification schema above for the record shape):

1. **Suggested required**
2. **Suggested machine-specific**
3. **Detected secret/identity**
4. **Candidate obsolete**
5. **Unknown**

Only Cliff's own reviewed classification (`classification.status`, via the
fields above) is authoritative. A difference the tool can't confidently
sort defaults to `unknown` on both `tool_suggestion` and
`classification.status` — it is never forced into a more specific bucket
to make the report look more complete than the evidence supports.

## Scheduling coverage (v2)

"Baseline service account only" (v1) missed root-installed maintenance.
Now inventories: system cron directories, `/etc/crontab`, root's crontab,
explicitly allowlisted service-account crontabs (Baseline's own, plus any
Cliff adds to the allowlist), and systemd timers. Command arguments and
environment assignments inside crontab entries are sanitized (any argument
shaped like a URL, path, or token/secret is tokenized; env var *names* are
kept, values redacted unless on a safe allowlist). The presence of any
*other* user's crontab is recorded (`ls /var/spool/cron/crontabs/`) without
reading its contents unless that specific user is separately approved.

## Read-only guarantee and write safety (v2)

Precise wording per Cliff's correction: **no host configuration or
operational state is modified; the only write is the explicitly selected
output file.** That one write is itself constrained, implemented in
`baseline/lib/inventory/pathsafety.py` (`validate_output_path()` +
`atomic_write()`):

- **Refuses** an output path inside the repository checkout, `/etc`,
  `/var/lib/baseline`, or `/etc/pve` — the tool will not let its own
  output land somewhere that could be mistaken for live config or get
  committed accidentally. Per correction #9, `validate_output_path()`
  resolves the requested path and all existing parent directories with a
  single `os.path.realpath()` call before the forbidden-location check,
  so a symlink into the repo or a protected directory, or a `..`
  traversal, is caught rather than bypassed.
- **Mode `0600`** on the created file, always.
- **Refuses to overwrite** an existing manifest at the target path unless
  called with an explicit `--overwrite` flag.
- **Atomic write:** `atomic_write()` re-validates the resolved path
  immediately before writing (independent of the earlier check, since the
  output directory could in principle be replaced in between), then
  writes to a temp file in the same directory as the final target via
  `tempfile.mkstemp`, `fsync`s it, `chmod`s it `0600`, and `os.replace()`s
  it into place — never a partial file visible at the final path.
- **On any failure**, the temp file is deleted before the process exits —
  no incomplete output left behind.
- Documented explicitly in the code as best-effort within what pure
  Python can guarantee, not a claimed full TOCTOU close — the test suite
  (`test_pathsafety.py`, 13 tests) covers the symlink, traversal, and
  overwrite-between-check-and-write cases correction #9 asked for, but a
  sufficiently well-timed concurrent filesystem attacker is outside what
  any of this can fully rule out.

## Sysctl handling (v2, tightened in round 4)

Read intentional keys from `/etc/sysctl.conf` and `/etc/sysctl.d/*.conf`
(parsed, not grepped) and record them all as `discovered_keys` — by name
only. **Only a small, separately reviewed Baseline allowlist**
(`SYSCTL_ALLOWLIST` in `collectors/security.py`, starter set:
`net.ipv4.ip_forward`, `net.ipv6.conf.all.disable_ipv6` — not exhaustive,
confirmed before this became a real host) **ever gets its live value
queried**, each as `["sysctl", "<key>"]`, one argument-array element per
key, **never** a shell string and never `sysctl -a`. A key merely
appearing in a config file no longer earns it a live query on its own —
round 3's version queried the union of discovered and allowlisted keys,
which meant an unreviewed key from a config file got its live value read;
Cliff's round-4 correction closed that. A malformed key (fails to parse
as a valid sysctl key shape) is recorded in the manifest as skipped, with
the reason, and never passed to `sysctl` at all.

## Python module/CLI layout (as built)

Implemented in Python, per Cliff's instruction. Consolidated somewhat
from the original per-category-file sketch — several categories were a
handful of lines each, so they're grouped by theme instead of one file
per row of the scope table above. `runner.py` is local, not a re-export
of `repair.Runner` (correction #2). Actual layout:

```
baseline/lib/inventory/
    __init__.py
    runner.py              # local Runner/RealRunner - bounded run()/read_text()/
                            # listdir()/walk_bounded(), shutil.which() for detection
    redact.py               # injectable-key HMAC Redactor
    pathsafety.py            # output-path validation + atomic write
    schema.py                 # manifest shape, injectable clock, to_json()
    tools_manifest.json        # the five-tool config, shown in full above
    manifest.py                 # orchestrates every collector -> schema -> atomic write
    collectors/
        __init__.py
        system.py           # packages (+ batched Conffiles), apt, platform_versions,
                             # firmware_drivers, systemd_units, kernel_udev, runtimes
        network.py            # interfaces closure, DNS
        storage.py             # storage (mounts/blocks) + boot (grub/cmdline/EFI)
        security.py             # firewall_sysctl_dns_time + journald
        scheduling.py             # cron + systemd timers
        baseline_config.py         # /etc/baseline + bounded /var/lib/baseline walk
        proxmox.py                  # /etc/pve field-by-field reads, pvesm/pvecm,
                                     # repo/subscription state - no pvesubscription get
        tools.py                     # tools_manifest.json-driven detection
        status_notes.py               # shared "_collection_notes" helper (round 4)
    validate.py                 # pre-run validator, round 4 - reads only, never writes
baseline/bin/baseline-drive-inventory
    # thin CLI wrapper:
    #   baseline-drive-inventory collect --source current-drive
    #                              --out <path> [--overwrite] [--node NAME ...]
    #   baseline-drive-inventory validate --manifest <path>
```

`diff.py` (two-manifest comparison → diff/classification records) is
**not** part of this pass — there's only one manifest to produce until a
real host and a disposable VM both exist to compare, so building the
diff engine now would be untestable against real shapes. Proposed as the
next slice once both sides of the comparison exist.

Each `collectors/*.py` function degrades independently (`{"available": False, "reason": ...}`
or an empty structure, plus a `"_collection_notes"` list recording *why*
any field came back empty — round 4) rather than raising, so one failing
category never aborts the whole run — the same graceful-degradation
principle `hardware.py` already uses.

## Test plan (as built) — 74 tests, all passing

`tests/unit/inventory_tests/`, `FakeRunner`-based (no real subprocess/
filesystem/network access), with its own local `fake_runner.py` — not
`tests/unit/fake_runner.py`, which lives on the repair branch (same
no-cross-branch-dependency reasoning as `runner.py`). Coverage, by file:

- **`test_redact.py`** (7 tests) — stable-within-run tokens, different
  keys across runs produce different tokens, different values produce
  different tokens, the default constructor uses a random key each
  instance, a token never contains the raw value, `None` passes through,
  and `fields_redacted` counts unique tokenized values.
- **`test_pathsafety.py`** (13 tests) — refuses paths inside the repo
  root/`/etc`/`/var/lib/baseline`/`/etc/pve`; refuses a symlink at the
  final path and a symlinked parent directory pointing into a forbidden
  root; refuses `..` traversal; refuses overwrite without the flag and
  allows it with the flag; a normal new path succeeds; `atomic_write()`
  creates mode `0600`, leaves no temp file behind on success, and
  independently refuses a symlink or missing-`--overwrite` state even
  when called directly (proving its re-validation doesn't rely on
  `validate_output_path()` having run first).
- **`test_runner.py`** (8 tests) — a missing binary is `unavailable`, not
  an exception; a real timeout is recorded, not raised; output is capped
  and flagged truncated; a missing file read is `unavailable`;
  `walk_bounded()` respects both max entries and max depth; `which()`
  goes through `shutil.which()`, confirmed via a monkeypatch spy.
- **`test_proxmox.py`** (14 tests) — `storage.cfg` drops secret-shaped
  keys and keeps allowlisted ones; `datacenter.cfg` records unknown
  fields as names/counts only, never values; node names and VMIDs are
  tokenized (never raw), consistently within one run; **the collector
  never calls `listdir`/`read_text` on any path containing `priv` at
  all** (correction #10, asserted directly against the FakeRunner's call
  log, not just against a graceful failure); a `net0` line keeps its
  bridge and drops its MAC; `pvesubscription` is never invoked and
  subscription status is `"unavailable"` with a reason; the repo-channel
  enabled/disabled state is still reported; `pvesm status` keeps
  structure and drops live usage columns; firewall addresses are
  tokenized while protocol/port survive; cluster detection reports
  standalone vs. clustered without inventing `pvecm status` parsing.
- **`test_system.py`** (3 tests) — `${Conffiles}` is queried in exactly
  one batched `dpkg-query` pass regardless of package count; `dmidecode`
  output keeps only allowlisted BIOS/system fields and drops a serial
  number and a UUID even from the raw text; a fully-missing toolset
  degrades to `None`s, not an exception.
- **`test_scheduling.py`** (3 tests) — other users' crontabs are counted
  and tokenized, never named; cron command arguments are sanitized; the
  allowlisted `baseline` service account's crontab is included.
- **`test_manifest.py`** (5 tests) — a fixed key + fixed clock produce
  byte-identical JSON across two runs; the default (no redactor passed)
  path produces a *different* token per run, matching real production
  behavior; the same key within one run produces the same token as an
  independent `tokenize()` call for the same value; `write_manifest()`
  refuses a forbidden output path and, on a normal path, writes valid,
  re-loadable JSON.
- **`test_security.py`** (4 tests, round 4) — a key merely discovered in
  a config file is never queried unless it's also on the reviewed
  allowlist; reviewed keys still get live values; a key that's both
  discovered and reviewed appears in both `discovered_keys` and
  `values`; an unavailable firewall backend (`nft`/`iptables`) is
  reported via `_collection_notes`, not just a `None` backend.
- **`test_validate.py`** (16 tests, round 4) — a clean manifest passes; a
  missing or wrong `schema_version` fails; output-file permissions are
  checked against a real file on disk (`0644` fails, `0600` passes); a
  forbidden-shaped key name (`password`) anywhere in the manifest is
  caught, while this tool's own `vmid_token`/`name_token` fields are not
  false-flagged; a raw IPv4, MAC, UUID, embedded URL credential, private
  key marker, SSH key, and Proxmox-subscription-key-shaped string are
  each independently caught; an oversized text value is flagged as
  advisory only, not a hard failure; degraded categories
  (`available: false`, non-empty `_collection_notes`, etc.) are collected
  for human review; the validator itself never writes to the manifest
  file it's checking.

## What this design still leaves open, for Cliff to confirm

- `datacenter.cfg`'s exact key set (starter allowlist in
  `collectors/proxmox.py`, not validated against a real file from this
  session) — its unknown-field handling is already fail-closed regardless
  of the exact set (round 4).
- The final sysctl allowlist beyond the two starter keys shown — now that
  discovered keys are never queried on their own (round 4), widening this
  allowlist later is the only way to get a new key's live value, so it's
  worth deciding early which keys matter.
- Whether the validator's `secret_value_patterns` regexes (particularly
  the Proxmox-subscription-key shape, which this session has never seen a
  real example of) need adjusting once run against real host data.
- Whether the "obsolete" suggestion's future codebase cross-reference
  should also check Guardian Plane, not just this repo (default: this
  repo only) — moot until `diff.py` exists.

## First-run procedure (for Cliff, or a physically/VM-connected session)

The collector, validator, and 74-test suite are implemented and passing
on this branch. **This session has not run any of it against the real
current-drive host** — no physical/VM access — so everything below is
written for whoever does have that access, per Cliff's operational
ordering. Nothing in this procedure commits or uploads anything; every
step is local until an explicit, separate decision to share.

1. **Freeze the current drive.** Stop making package or configuration
   changes to the current BaselineOS drive — no `apt install`/`upgrade`,
   no edits under `/etc/pve` or `/etc/baseline`, from this point until
   the manifest and probe below are both captured.
2. **Take a cold image or recoverable clone**, if practical, before any
   integration-related modification. The manifest records what should or
   shouldn't be reproduced; the image preserves everything else, in case
   the manifest misses something it wasn't designed to capture.
3. **Boot the current drive normally**, then mount a dedicated external
   output location (a removable drive or a directory that is *not* this
   git checkout, not `/etc`, not `/var/lib/baseline`, not `/etc/pve` -
   `pathsafety.py` refuses all of those anyway, but pick a real external
   path up front). Example: `/mnt/baseline-audit/` on a USB drive.
4. **Run the inventory command:**
   ```
   sudo /opt/baseline/bin/baseline-drive-inventory collect \
       --source current-drive \
       --host-label "dell-latitude-5290-<today's date>" \
       --node <this host's actual Proxmox node name> \
       --out /mnt/baseline-audit/current-drive-manifest.json
   ```
   (`--node` inventories that node's `/etc/pve/nodes/<node>/{qemu-server,lxc}/`
   configs, tokenized — never its `priv/` directory. Omit `--node`
   entirely if you'd rather not inventory VM/CT configs on this pass.)
   This needs to run as root (or with read access to `/etc/pve`), since
   `/etc/pve` and several `/proc`/`/etc` paths this collector reads are
   root-only.
5. **Run the narrow repair-environment probe** (already in PR #1, a
   separate script, separate output):
   ```
   sudo /opt/baseline/boot/baseline-repair-env-probe.sh \
       > /mnt/baseline-audit/repair-env-probe.txt
   ```
6. **Validate the inventory output locally**, before looking at it or
   moving it anywhere:
   ```
   /opt/baseline/bin/baseline-drive-inventory validate \
       --manifest /mnt/baseline-audit/current-drive-manifest.json
   ```
   This prints a JSON report and exits non-zero if any hard check fails
   (schema, file permissions, forbidden field names, or secret-shaped
   values). **A passing validator is defense in depth, not authorization
   to upload or commit the manifest anywhere** — it can't catch
   everything a human reading the actual content can.
7. **Review the redaction report and degraded-categories list by hand.**
   The manifest's own `redaction_report.fields_redacted` count is a
   sanity check (a suspiciously low number for a real host suggests
   something didn't tokenize that should have). The validator's own
   `degraded_categories_reported` list names every category that came
   back `available: false`, timed out, was permission-denied, or was
   truncated — read through it and confirm each one is expected (e.g.
   `subscription_status: unavailable` always shows up by design; a
   `permission_denied` on `/etc/pve/storage.cfg` while running as root
   would not be expected and is worth investigating before trusting the
   rest of the manifest).
8. **Manually inspect both output files directly** (`less`/`cat` the
   JSON and the probe's text output) before sharing either one anywhere
   - the validator and the probe's own redaction are both automated
   checks, and this is the step Cliff asked to keep as a human one.
9. **Files that should result** from this procedure, all under the
   external output location chosen in step 3, none of them inside this
   git checkout:
   - `current-drive-manifest.json` (mode `0600`, from step 4)
   - `repair-env-probe.txt` (from step 5)
   - the validator's JSON report (redirect step 6's stdout to a file if
     you want to keep it, e.g. `current-drive-manifest.validate.json`)
   - the drive image/clone from step 2, wherever that tooling puts it
     (outside the scope of this collector)
10. **None of these should be committed to git or uploaded anywhere yet.**
    They stay on the external output location until Cliff (or whoever
    reviewed them in step 8) explicitly decides to share them — e.g. by
    attaching the manifest to a message, or by adding a *new*,
    deliberately chosen subset of it to a future commit. This tool never
    does that on its own; its only write is the one manifest file at the
    path you gave it in step 4.

Once a real current-drive manifest exists and has been reviewed, the
remaining sequence (unchanged from Cliff's original ordering) is: build
the disposable Proxmox VM, run the same `collect` command against it,
then build `diff.py` (see "Diff/classification schema" above - deferred,
not yet built) to compare the two manifests. Only after that does the
boot-recovery-service design proceed, using the probe's output, built and
tested in the disposable VM first.

**This session's limitation applies exactly as before:** no reachable
Proxmox/Debian host, so this branch could design, implement, and validate
the collector, but cannot run any of the steps above itself. They are
Cliff's, or a physically/VM-connected session's, to perform.
