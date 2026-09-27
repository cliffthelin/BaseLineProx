# Guardian: An Ubuntu 26.04 System Control Plane (formerly "USB Guard" spec)

## TL;DR — architecture pivot from pass 1
This spec now targets a **control plane**, not a single expanded utility. Your existing USB-freeze detection becomes **I/O Guardian**, the first of several modules under a shared daemon ("Guardian") that GNOME, Xfce, a TUI, a CLI, and a tray indicator all talk to. Core decisions carried forward from research pass 2:
- **Rust for the privileged daemon.** Given this machine's incident history (a mass chown/chmod took down sudo; a single typo in a systemd symlink caused a boot loop), a privileged component should not be a large Python codebase run as root. Rust's ownership model closes whole classes of the memory-safety and error-handling bugs that turn "small mistake" into "unbootable system." GUI/TUI/CLI/indicator share the daemon's D-Bus API and can be Rust (GTK4-rs, Ratatui) for one shared language, or a lighter frontend language if that's faster to ship — the daemon's privilege boundary is what actually needs to be Rust.
- **Orchestrate, don't reimplement.** Ubuntu 26.04's default image already ships a strong diagnostic substrate — BCC/eBPF tools, `bpftool`, `bpftrace`, `sysprof`, `sysstat`, `trace-cmd`, `systemd-oomd`, `thermald`, udev, UDisks2, UPower, fwupd, AppArmor, GNOME Logs, and the new Rust/GTK4/libadwaita **Resources** app (a genuinely good UI reference to study, not duplicate). A **Capability Registry** should discover what's present at startup and prefer native D-Bus/library APIs over scraped CLI output, in that order: D-Bus/library → kernel interface (`/proc`, `/sys`) → structured CLI → scraped CLI (last resort).
- **Target 26.04.1, not the original April image.** Confirmed: Ubuntu 26.04.1 LTS shipped August 27, 2026, rolling in security fixes through August 25. Since this machine is already installed and kept updated via `apt`, the point release changes nothing about what's on disk — it only matters for fresh installs — but it's the right baseline to develop and test against going forward.
- **Every risky action follows Snapshot → Validate → Apply → Observe → Confirm → Commit-or-Rollback.** This is NetworkManager's own checkpoint/rollback pattern (a network change is applied against a checkpoint and auto-reverted if not confirmed within a timeout) generalized as Guardian's core safety principle for any write action, not just networking.

## Key Findings (pass 2, layered onto pass 1)

1. **Correlation beats single-metric alerting.** The most valuable output isn't "USB disk busy" or "CPU 90%" — it's an evidence chain: physical port → device → block device → filesystem → mount → processes waiting → latency → kernel errors → system-wide pressure, collapsed into one finding with a confidence level. This applies identically to I/O, thermal, and boot-time bottlenecks.
2. **PSI (`/proc/pressure/{cpu,memory,io}`) is the foundational signal, not a nice-to-have.** It distinguishes "95% disk utilization, nobody waiting" (healthy) from "40% utilization, full-pressure climbing" (real problem) — something raw utilization percentages cannot do. This should sit underneath every module, not just bottleneck detection.
3. **Diagnostics should escalate in cost and back off when the machine is already struggling.** Tier 1: cheap always-on telemetry (PSI, diskstats, thermal, journal events). Tier 2: per-process I/O detail on anomaly. Tier 3: temporary eBPF (`biolatency`, `biosnoop`, `runqlat`, `opensnoop` via bpftrace/BCC, both present on the default 26.04 image). Tier 4: `trace-cmd`/Sysprof/KernelShark for genuinely hard incidents. A stalling machine should never have its own diagnostic layer making things worse by writing heavy trace files — keep the always-on path tiny, in-memory, and lock/allocation-light.
4. **Recovery actions need explicit, visible risk tiers**, not a flat settings list. For USB/storage specifically, UDisks' own `power-off` operation already does the safe sequence — confirms nothing is using the drive, flushes buffers/cache, then deconfigures the USB device and disables its upstream hub port — which is a far better default than a raw controller reset. A five-tier ladder (Observe → Low → Moderate → High → Very High) with the top two tiers visually separated as "Recovery / Advanced" keeps casual users away from destructive actions while still exposing them.
5. **The naming collision is real and worth resolving deliberately.** Ubuntu packages an actual `usbguard` (device authorization/security framework, not on the desktop image by default) that is unrelated to your I/O-freeze-detection tool. Recommendation: rename your module internally to **I/O Guardian**, and treat upstream USBGuard as a separate, optional **USB Security** module that wraps its real D-Bus API (detailed in §8 below) rather than colliding on the name.
6. **Don't fight existing daemons for write ownership.** If `thermald` owns CPU thermal policy, or a tool like CoolerControl already owns a fan channel, Guardian should observe, not simultaneously write. This "single-writer rule" prevents exactly the kind of conflicting-control bug class that caused problems earlier in this system's history (two things trying to manage the same resource).
7. **Deduplicated logs need a "Log Lens," not lossy deletion.** The raw systemd journal should remain the untouched, authoritative source; a Log Lens layer groups exact and *normalized* duplicates (masking volatile fields like PID/timestamp/sequence, but preserving meaningful dimensions like device ID, error code, or service name) into incident rows with count + first/last timestamp, expandable back to raw events. This satisfies the original ask (collapse 400 identical lines into one row with counts) without destroying forensic evidence the raw approach in the first draft of this spec would have discarded.
8. **The incident recorder must never depend on the thing it's diagnosing.** If Guardian's own critical-incident logging writes to a monitored external/USB drive, a frozen USB device can freeze the tool trying to record that the USB device froze. Use an in-memory ring buffer plus a small quota-capped `/var` location; let users export bundles to other storage afterward, never write critical incident data live to removable media.
9. **Session switching should discover the active display/session manager, not assume one.** This machine currently runs LightDM with both Xfce and GNOME sessions; a stock 26.04 image ships GDM. Guardian must read `/usr/share/xsessions/` and `/usr/share/wayland-sessions/`, write through AccountsService (with `.dmrc` as fallback, matching §2 below), and avoid hardcoding either display manager's config format.
10. **The desktop panel indicator should escalate rarely and stay tiny** — a default "✓ Guardian — Healthy" state, changing only when something is actually actionable ("⚠ Guardian — I/O pressure"), with the click menu surfacing the two or three most relevant items plus "Open full dashboard." Complexity belongs in the full app, not the tray.

## Architecture

### Component split

| Component | Responsibility | Runs when |
|---|---|---|
| `guardian-daemon` | Privileged observation, transactions, recovery actions, hardware adapters, Capability Registry | Before login, always-on |
| `guardian-gui` | GTK4/libadwaita control center (GNOME + Xfce) | Logged-in session |
| `guardian-tui` | Same status/controls from terminal, SSH, or a recovery console | Anytime, including pre-login emergency access |
| `guardian-indicator` | Minimal tray/header icon via StatusNotifierItem, alerts, quick actions | Desktop session |
| `guardian-cli` | Scripting, automation, diagnostics | Anytime |
| `guardian-recorder` | Very-low-overhead flight recorder for freezes/incidents (in-memory ring buffer + quota'd local storage, never on monitored removable media) | Boot onward |

The GUI/TUI/CLI/indicator are never the privileged surface — they're all thin clients over the daemon's D-Bus API, authorized per-action via polkit, exactly as polkit is designed for: an untrusted client talking to a privileged mechanism over IPC, with authorization applied per-action rather than per-process. Ubuntu 26.04 ships polkit and the standard system D-Bus infrastructure needed for this.

**Polkit action namespacing (concrete):**
```
org.guardian.storage.poweroff
org.guardian.service.restart
org.guardian.logs.configure
org.guardian.session.set-default
org.guardian.thermal.set-power-cap
org.guardian.usb.authorize-device
```
Each is independently grantable — "run the whole app as root" is exactly the failure mode this avoids.

### Capability Registry — prefer the most authoritative interface per domain

| Area | Preferred integration | Role |
|---|---|---|
| Services/boot | systemd D-Bus | State, restart, dependencies, failure |
| Runtime constraints | systemd/cgroup v2 (`MemoryHigh`, `MemoryMax`, IO weight/bandwidth ceilings) | Throttle before killing |
| System pressure | `/proc/pressure/*` | Real CPU/memory/IO stalls, not just utilization |
| USB/block devices | udev + UDisks2 D-Bus | Topology, mounts, safe isolation |
| Storage stats | `/proc/diskstats`, sysstat | Baseline monitoring |
| Deep I/O diagnosis | BCC/eBPF (`biolatency`, `biosnoop`, etc.) | Escalation tier, not always-on |
| General resources | `/proc`, `/sys`, GNOME Resources as UI reference | Dashboard |
| Thermals | hwmon/sysfs + thermald | CPU/platform temperature, respecting single-writer rule |
| Power | power-profiles-daemon (or `tuned-ppd` if advanced tuning is added later) | Normal power policy |
| Battery | UPower D-Bus | Battery/UPS telemetry |
| NVIDIA GPU | NVML | Temperature, power, and — critically — the actual throttle *reason*, not just the reading |
| Storage health | UDisks + optional smartmontools/nvme-cli | SMART/NVMe health |
| Firmware | fwupd | Firmware inventory/update |
| Network | NetworkManager D-Bus | Health, config, checkpoint/rollback pattern |
| Logs | journald API | Source of truth; Log Lens is a view over it, never a replacement |
| Desktop session | AccountsService (`.dmrc` fallback) | Next-login GNOME/Xfce selection |
| Updates | apt/PackageKit | Update and package state |
| Certification | `hwctl` (confirmed: checks Ubuntu Hardware Certification status against Canonical's database via `hw.ubuntu.com`; requires root for SMBIOS collection; being migrated from a `.deb` to a strictly-confined snap around the 26.04.1/26.10 timeframe) | Informational "Hardware / Compatibility" page — not a control surface |

## Module Details

### I/O Guardian (your existing tool, upgraded)

**Correlation chain to build, in order:** physical USB port → USB device → block device → partition → filesystem → mount → processes with open handles → I/O latency → kernel error events (e.g. UAS timeouts/resets) → system-wide PSI. This is what turns "`/dev/sdg` is busy" (useless) into "USB device 2-3 has 14-second block requests, system I/O full-pressure is rising, `uas` has issued two resets, 17 processes are blocked" (actionable), which is the actual signature of the freeze class this tool was built to catch.

**Recovery ladder (ascending risk, UI should visually separate the last two tiers):**

| Risk | Action |
|---|---|
| Observe | Alert, collect evidence, no system change |
| Low | Temporarily throttle the offending workload via cgroup `IOWeight`/`IOReadBandwidthMax` |
| Low | Ask the writing application/service to pause |
| Moderate | Clean unmount of the affected filesystem |
| Moderate | UDisks safe power-off (flush → deconfigure → disable upstream hub port) |
| Moderate | Remount read-only where appropriate |
| **High (Recovery/Advanced)** | Kill a process stuck against the device |
| **High** | Forced/lazy unmount |
| **Very High** | USB deauthorize/reauthorize/reset |
| **Very High** | Driver/module intervention |

Every action, at every tier, follows Snapshot → Validate → Apply → Observe → Confirm → Commit-or-Rollback — the same discipline NetworkManager already applies to config changes.

### Observability / Bottleneck Detection

**Evidence-chain output format** (what the GUI/CLI should actually render, not a bare metric):
```
Current bottleneck: USB storage
  System I/O full-pressure: elevated
  /dev/sdh latency: abnormal
  Physical device: USB 3-2
  Blocked requests: 71 | Affected processes: 4
  Kernel: 6 repeated UAS timeout/reset events
  Began: 14:37:18 — Last occurrence: 14:39:04
  Confidence: HIGH
```
```
Current bottleneck: GPU thermal limit
  GPU utilization: 98%
  NVML reports: thermal-clock limiting active
  CPU/IO pressure: normal
  Confidence: HIGH
```
NVML exposes not just temperature but the actual hardware/software throttle-reason bitmask, which is what lets Guardian say "slow because thermally throttled" instead of just "GPU is busy."

**Runtime throttling before killing:** cgroup v2 via systemd — `MemoryHigh` is explicitly a soft throttling mechanism (reclaim pressure, not instant OOM), with `MemoryMax` as the last-resort hard ceiling; IO weight and per-device read/write bandwidth caps work the same way. Apply these as **transient scopes via systemd's D-Bus runtime API**, not permanent unit-file edits — that keeps every intervention reversible.

**Boot-time bottleneck detection with a real baseline, not a bare number:**
`systemd-analyze time/blame/critical-chain/plot` are the raw inputs, but `blame`'s own documentation warns it can mislead — a unit may look slow while it's actually just waiting on something else. Correlate the critical-chain path against mounts, device init, udev, kernel messages, disk latency, fsck activity, network state, and thermal throttling, and compare against the machine's own rolling history:
```
Boot 42: 31.4s
Last-10-boot baseline: 18–21s
Regression begins after USB disk X was connected
Device initialization accounts for +10.8s
```

### Thermal & Power

**Single-writer rule (non-negotiable):** if `thermald` owns CPU thermal response, Guardian observes CPU thermals but does not also write control values. Where the user wants dedicated fan/GPU control, use existing specialized tools as optional providers rather than reimplementing their (genuinely risky) low-level logic: **CoolerControl** discovers hwmon/NVML/liquidctl devices and explicitly distinguishes read-only sensors from truly controllable channels; **LACT** already covers AMD/NVIDIA/Intel GPU monitoring, history, power caps, throttle reasons, and fan curves. Guardian's job is to surface their state in the unified dashboard and defer control to them, not to duplicate PWM-writing code paths.

**Read-only telemetry to aggregate regardless of provider:** CPU/package/core temps, motherboard/hwmon sensors, fan RPM, NVMe/drive temperature, battery/UPS temperature via UPower, GPU core/memory/hotspot data where supported, thermal zones, active power profile, and actual clock throttling with vendor-reported reasons (not just raw MHz).

**Where this system's own history sets policy defaults:** hard-coded thermal thresholds (e.g., "reduce load at 85°C, stop at 90°C" for a given GPU) should become a per-machine **Thermal Policy profile**, not a global default — the engine should prefer manufacturer-reported safe operating thresholds where available and treat hard-coded numbers as an override, not the baseline.

### Logs — "Log Lens" over an untouched journal

Two layers:
1. **Raw Evidence** — the systemd journal, untouched, remains authoritative. journald's existing caps (`SystemMaxUse`, `SystemKeepFree`, `SystemMaxFileSize`, `RuntimeMaxUse`, `MaxRetentionSec`) plus systemd 259's `LogsDirectoryQuota=` (where the filesystem supports project quotas) already provide most of the disk-space protection this project needs — expose sane policy through the GUI rather than inventing a parallel rotation engine.
2. **Log Lens** — Guardian groups exact and normalized-pattern duplicates into incident rows:

| Pattern | Count | First | Last |
|---|---:|---|---|
| UAS command timeout `{device}` | 83 | 14:02 | 14:49 |
| NVIDIA Xid `{code}` GPU `{n}` | 6 | 14:11 | 14:44 |
| USB device reset `{port}` | 19 | 14:03 | 14:48 |

Normalize volatile fields (PID, timestamp, sequence number, memory address) out of the pattern fingerprint, but keep meaningful dimensions (device, error code, service) *in* it — collapsing across those would hide real distinctions. Clicking a row expands to the underlying raw journal events. This is the refined version of the "×417, first/last timestamp" collapsing behavior from the original ask — same outcome, but the source data is never destroyed, only re-presented.

For the CUPS-style incident specifically (a non-journald flat text log growing faster than daily rotation can catch): keep the four-layer defense from pass 1 — fix the app-level root cause (CUPS `LogLevel warn`, `MaxLogSize` reasonable and non-zero, `AccessLogLevel config`), hourly not daily logrotate with `maxsize`, and a real-time inotify watchdog per configured path as the backstop layer that catches growth between rotation cycles. See §6 below for the exact `cupsd.conf`/`journald.conf`/`logrotate` snippets and the inotify-shim pseudocode.

**Incident recorder placement rule:** ring buffer in memory + small quota-capped local `/var` storage only. Never the active write target for Guardian's own critical logging on a monitored removable/USB disk — that creates the exact self-referential freeze this tool exists to catch.

### Session / Desktop Environment Switching

GNOME's documented mechanism stores the user's default session via **AccountsService**, consumed at next login unless overridden at the greeter. Guardian should:
1. Enumerate `/usr/share/xsessions/*.desktop` (X11 — Xfce lives here) and `/usr/share/wayland-sessions/*.desktop` (Wayland — GNOME lives here on 26.04, which is Wayland-only).
2. Write the choice through AccountsService (`SetSession`/`SetXSession` on the user's D-Bus object), with `~/.dmrc` written as a fallback — AccountsService wins when both are present, so keep them in agreement.
3. Discover the *actual* active display/session manager at runtime rather than assuming GDM (stock 26.04) or LightDM (this machine's actual current setup) — do not hardcode either's config format.
4. Present it as: **Current:** Ubuntu GNOME/Wayland · **Next login:** Xfce/X11 · **Apply:** Log Out | Reboot Later | Reboot Now. Logout is sufficient in almost all cases; don't force a reboot the user doesn't need.

**Pre-login access, done safely:** do not embed the full Guardian GUI into the greeter (GDM or LightDM). Instead: the privileged daemon starts early in boot, before the graphical greeter; emergency access is via VT switch (Ctrl+Alt+F-key) to `guardian-tui`, or a boot-menu "Guardian Recovery" entry. A longer-term option worth designing toward: a minimal systemd target that starts storage/udev/network/Guardian but deliberately does not start GNOME/Xfce — genuinely useful for the display-driver/session-config class of failure this machine already hit once.

### Desktop Indicator

StatusNotifierItem/AppIndicator remains the right implementation choice — it's the common denominator both GNOME (via the `appindicatorsupport@rgcjonas.gmail.com` extension, shipped and enabled by default on Ubuntu's GNOME image) and Xfce (native StatusNotifier support in the panel) can render from one backend. See §1 below for the concrete GTK3 + `AyatanaAppIndicator3` implementation notes, package dependencies, and autostart wiring.

Keep the indicator itself minimal: default **"✓ Guardian — Healthy,"** changing state only on something actionable (**"⚠ Guardian — I/O pressure"**), with a short click-menu (current warnings, "Safe-isolate device…," "Start incident capture," "Switch desktop next login…," "Open full dashboard") rather than trying to surface the whole app from the tray.

## Existing Open-Source Projects — what to borrow vs. what to build

| Project | What to take from it | Role for Guardian |
|---|---|---|
| GNOME Resources | GTK4/Rust resource-monitor UI patterns | Strong UI reference |
| Cockpit | Modular Linux-admin architecture (storage/services/network as separate modules over D-Bus) | Strong architecture reference — but it's web/server-oriented; don't turn Guardian into a second Cockpit |
| Netdata | Metric schemas, PSI/eBPF correlation concepts, alerting model | Optional collector/reference, ~100–150MB RAM overhead if run standalone |
| PCP | Long-term performance history/replay | Optional advanced history backend |
| atop | Historical process/resource accounting, good for post-incident forensics | Optional |
| btop | Dense, well-designed TUI information layout | Direct TUI design inspiration for `guardian-tui` |
| Glances | Plugin/TUI architecture | Reference only — Ubuntu 26.04 currently ships 4.3.3, and a 2026 server-mode vulnerability fixed upstream in 4.5.3 has Resolute's status marked "Needs evaluation"; don't depend on it as an exposed service today |
| CoolerControl | hwmon/NVML/liquidctl sensor+control integration, explicit read-only-vs-controllable distinction | Optional thermal control provider, respecting the single-writer rule |
| LACT | GPU telemetry/control across AMD/NVIDIA/Intel | Optional GPU control provider |
| KernelShark | Deep kernel trace visualization | Expert-tier escalation launch-out, not embedded |
| tuned/tuned-ppd | Advanced, arbitrated performance profiles; Ubuntu ships `tuned-ppd` specifically as a power-profiles-daemon-compatible bridge | Optional, only if it doesn't fight the single-writer rule against `thermald`/power-profiles-daemon |
| USBGuard | Real USB device authorization/security — see §8 for its actual D-Bus API, config paths, and rule syntax | Separate optional **USB Security** module, distinct from I/O Guardian |
| Your current tool | I/O-failure detection and recovery philosophy | **Becomes the core of I/O Guardian**, upgraded per this spec |

**PCP, `atop` 2.12.1, `iotop-c` 1.31, and `btop` 1.4.6 are all available in the 26.04 (Resolute) archive** as of this research pass — useful to know these don't require chasing down third-party PPAs.

## Recommendations — staged rollout, revised

**Phase 1 — Control Plane.** Rust daemon, D-Bus API surface, polkit action definitions, Capability Registry, GTK4 shell skeleton, TUI skeleton, indicator, and a transaction/audit log for every privileged action taken (this audit trail is what makes "what changed and why" answerable after an incident, instead of reconstructing it from photos of a terminal after the fact).

**Phase 2 — I/O Guardian.** Migrate your existing detection logic in; add the UDisks/udev/PSI correlation chain, the recovery ladder, and the incident recorder (ring buffer + quota'd local storage, never on monitored media).

**Phase 3 — Observability.** PSI-first dashboards, process/resource views, boot-health baseline comparison, evidence-chain bottleneck output, cgroup-based throttle-before-kill.

**Phase 4 — Thermal & Power.** hwmon + thermald + power-profiles-daemon integration, NVML, storage temps, single-writer rule enforcement, per-machine Thermal Policy profiles, optional CoolerControl/LACT providers.

**Phase 5 — Logs & Incidents.** journald policy exposure, Log Lens (raw + deduplicated views), the four-layer disk-space defense from §6, bundled incident export.

**Phase 6 — System Management.** GNOME/Xfce session switching via AccountsService, service management, firmware (fwupd), network (NetworkManager), storage health, updates, `hwctl` certification status page, and — as a later, carefully-scoped goal — the pre-login "Guardian Recovery" systemd target.

**Explicitly deferred out of the normal-control tier** until the transaction/safety framework (Phase 1) has proven itself in practice: general fan overclocking, kernel parameter tuning, automatic driver changes, forced USB resets, and automatic service disabling. These stay behind the highest-risk tier of the recovery ladder, opt-in and logged, not defaults.

**The differentiator to hold onto:** observe the whole machine → correlate symptoms → explain the likely bottleneck with evidence → propose the least-disruptive corrective action → validate it → roll it back automatically if it fails. That ties this machine's actual incident history — USB freezes, thermal events, boot/session breakage, a runaway log filling the disk — into one coherent design instead of a drawer of unrelated utilities.

---

## Build Mechanics Reference

### 1. Cross-Desktop Tray/Menu Implementation

**Recommendation: GTK3 + `AyatanaAppIndicator3` for the tray surface specifically** (even though the rest of the GUI targets GTK4/libadwaita per the architecture above) — AppIndicator/SNI libraries remain GTK3-only; there is no reliable GTK4 equivalent yet. Run the indicator as a small GTK3 subprocess or library boundary within `guardian-indicator`, communicating with the Rust daemon over D-Bus like every other client.

**Library choice (concrete):**
- apt package `gir1.2-ayatanaappindicator3-0.1` (source `libayatana-appindicator`) — the maintained fork; the legacy Canonical `gir1.2-appindicator3-0.1` is effectively deprecated.
```python
import gi
try:
    gi.require_version('AyatanaAppIndicator3', '0.1')
    from gi.repository import AyatanaAppIndicator3 as AppIndicator3
except (ValueError, ImportError):
    gi.require_version('AppIndicator3', '0.1')
    from gi.repository import AppIndicator3
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk
```
(If the indicator client ends up in Rust instead, use the `libayatana-appindicator` C API directly via bindings, or implement `org.kde.StatusNotifierItem` on D-Bus directly — more code, no GTK3 dependency.)

**GNOME 50 side:** depends on `gnome-shell-extension-appindicator` (UUID `appindicatorsupport@rgcjonas.gmail.com`), shipped and enabled by default as part of `ubuntu-desktop`. GNOME's own "Status Icons" extension is XEmbed-only and will NOT render AppIndicator/SNI — don't rely on it. Under Wayland (GNOME 50's only mode on 26.04), extension state changes require logout/login, not `Alt+F2 r`.

**Xfce 4.20 side:** the panel's built-in Status Tray plugin implements SNI natively (`SnBackend`/`SnItem`/`SnButton`) — just ensure it's present on the panel; avoid running it alongside `xfce4-indicator-plugin` simultaneously, which has historically caused icon-stealing conflicts.

**Autostart wiring:** `/etc/xdg/autostart/guardian-indicator.desktop` (system-wide, honored by both DEs):
```ini
[Desktop Entry]
Type=Application
Name=Guardian
Exec=/usr/bin/guardian-indicator
X-GNOME-Autostart-enabled=true
NoDisplay=true
```
Package dependencies: `gir1.2-ayatanaappindicator3-0.1, gnome-shell-extension-appindicator, gir1.2-gtk-3.0` (plus GTK4/libadwaita deps for the main app).

### 2. Session/DE Switching — exact mechanics

AccountsService is authoritative when present; `.dmrc` is fallback only:
```bash
busctl call org.freedesktop.Accounts /org/freedesktop/Accounts \
  org.freedesktop.Accounts FindUserByName s "$USER"
busctl call org.freedesktop.Accounts /org/freedesktop/Accounts/User1000 \
  org.freedesktop.Accounts.User SetXSession s "xfce"
busctl call org.freedesktop.Accounts /org/freedesktop/Accounts/User1000 \
  org.freedesktop.Accounts.User SetSession s "ubuntu"
```
Also write `~/.dmrc`:
```ini
[Desktop]
Session=xfce
```
Both are next-login only; there is no live DE switch under Wayland.

### 3. Thermal/Hardware Read Paths

- **lm-sensors** (`sensors -j`), **nvme-cli** (`nvme smart-log`), **smartmontools** (`smartctl -a`/`-H`), **nvidia-smi**/NVML for GPU. Raw values live under `/sys/class/hwmon/hwmon*/` (`temp*_input`, `fan*_input`, `pwm*`).
- **Fan write access is dangerous and must be gated:** `pwmconfig` briefly stops each fan to map PWM→fan during setup; once a controller owns PWM it overrides BIOS/EC control. Guardrails: read-only by default; explicit polkit-gated arm mode; hard floor PWM (never allow full stop on CPU/GPU zones); sane MAXTEMP ceilings; dead-man's-switch reverting to `pwmN_enable=2` (BIOS auto) or full speed if the control process dies or a sensor reads invalid; alert + auto-revert if a controlled fan reports 0 RPM under load.

### 4. Restart-Loop Detection Mechanics

systemd already tracks this — defaults `DefaultRestartSec=100ms`, `DefaultStartLimitIntervalSec=10s`, `DefaultStartLimitBurst=5`; a unit crashing more than 5 times in 10 seconds enters `failed` with "start request repeated too quickly." Read `systemctl show <unit> -p NRestarts,ActiveState,SubState,Result` or subscribe to `org.freedesktop.systemd1` D-Bus signals rather than reimplementing the counter. **Placement gotcha:** `StartLimitIntervalSec`/`StartLimitBurst` belong in `[Unit]`; `Restart=`/`RestartSec=` belong in `[Service]` — verify with `systemctl cat <unit>` when writing overrides. Automated response should be Tier-1-only (stop + mark "paused by Guardian," never blind `reset-failed`-and-restart, never auto-`disable`) per the recovery-ladder philosophy above.

### 5. Log Deduplication — Generic Shim Design

Prior art: rsyslog's `$RepeatedMsgReduction` keys on PID and explicitly fails on high-volume logs from tools that spawn a fresh PID per cycle — exactly the crash-loop case this project needs to handle, so don't copy that design. The OpenTelemetry Collector `logdedup` processor's model is correct: window-based grouping on normalized content (resource attributes, scope, body, attributes, severity, event name — timestamp excluded), emitting one record with `log_count`, `first_observed_timestamp`, `last_observed_timestamp`. Reference pseudocode (content-hash based, works on arbitrary text logs via inotify tailing, not just journald):
```python
import inotify_simple, re, hashlib, time
NORM = [ (re.compile(r'\d{4}-\d\d-\d\dT[\d:.+-]+'), '<TS>'),
         (re.compile(r'\[\d+\]'), '[<PID>]'),
         (re.compile(r'0x[0-9a-f]+'), '<HEX>'),
         (re.compile(r'Job \d+'), 'Job <N>') ]
def normalize(line):
    for rx, repl in NORM: line = rx.sub(repl, line)
    return line
def key(line): return hashlib.blake2b(normalize(line).encode(), digest_size=16).digest()

state = {}
def ingest(line, out):
    k = key(line); now = time.time()
    if k in state:
        s = state[k]; s[0]+=1; s[2]=now
    else:
        state[k] = [1, now, now, line.rstrip()]
    flush_expired(out, now)
def flush_expired(out, now, window=10):
    for k in list(state):
        c,first,last,sample = state[k]
        if now-last > window:
            out.write(sample if c==1 else f"{fmt(first)}..{fmt(last)} (x{c}) {sample}\n")
            del state[k]
```
This is the engine behind Log Lens (§ above) — output feeds the collapsed view while raw journal/file data stays untouched.

### 6. Disk-Space-Protected Logging — Four Layers (CUPS incident, generalized)

**Root cause of the 400GB CUPS event:** CUPS' own `MaxLogSize` directive defaults to 1MB and auto-rotates at that size unless explicitly set to `0` (disabled) or raised very high — check for `MaxLogSize 0` in `/etc/cups/cupsd.conf` as the likely enabler. `AccessLogLevel` defaulting to `actions` also floods `access_log` with routine polling.

**Layer 1 — fix the app:**
```
LogLevel warn
MaxLogSize 50m
AccessLogLevel config
MaxClients 100
PreserveJobHistory No
PreserveJobFiles No
```
**Layer 2 — journald hard caps** (`/etc/systemd/journald.conf`):
```
Storage=persistent
SystemMaxUse=1G
SystemKeepFree=2G
SystemMaxFileSize=100M
RuntimeMaxUse=100M
MaxRetentionSec=30d
Compress=yes
```
Also worth exposing in the GUI: systemd 259's `LogsDirectoryQuota=` for per-service accounting where the filesystem supports project quotas.

**Layer 3 — logrotate, size-first, hourly not daily:**
```
/var/log/cups/*_log {
    hourly
    maxsize 100M
    rotate 5
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
    su root lp
}
```
**Layer 4 — inotify watchdog (the actual backstop):** a daemon watching configured paths, checking `st_size` against a per-path ceiling on every `IN_MODIFY`, truncating-in-place (preserving the writer's fd) the instant a ceiling is crossed — sub-second reaction, not hourly. This is the layer that would have caught the 400GB event in real time.

**Generalizable per-path policy schema (config the daemon enforces uniformly, any log source):**
```yaml
logpaths:
  - path: /var/log/cups/error_log
    max_size: 200M
    max_previous: 5
    reserve_free: 2G
    action: truncate   # truncate | rotate | alert_only
```
Default every path to `alert_only`; require explicit opt-in per path (or globally) to enable automatic `truncate`/`rotate`.

### 7. Smart Combination Features

**Crash-loop + log-throttle, combined:** when the systemd watcher (§4) sees a unit hit its start limit or `NRestarts` climb rapidly, automatically (a) identify that unit's log sinks (journald via `journalctl -u`, plus any file sinks mapped through `/proc/<pid>/fd` while alive), (b) apply the Log Lens collapse more aggressively to those specific sinks, and (c) pause the unit per the Tier-1 recovery response — addressing the exact double-failure mode (CPU burned on restarts *and* disk filled with identical log lines) in one motion instead of two separate fixes discovered independently, as happened on this machine.

**Thermal/resource-spike → culprit correlation:** on a PSI threshold crossing or thermal-ceiling breach, snapshot top processes by the relevant resource (CPU/RSS/IO) and attach that snapshot to the event record — `{event, timestamp, sensor_value, top_process}` — so the dashboard shows "CPU pkg hit 92°C at 14:03; top process: X (pid, %CPU)" as one correlated finding rather than three separate graphs the user has to mentally align.

### 8. USBGuard Integration (separate "USB Security" module)

Real framework, config in `/etc/usbguard/` (`usbguard-daemon.conf`, `rules.conf`, `rules.d/`, `IPCAccessControl.d/`), two systemd units (`usbguard.service` core, `usbguard-dbus.service` D-Bus bridge, required for any D-Bus client). **Critical setup-order warning:** generate an initial policy from currently-attached devices *before* first daemon start, or `ImplicitPolicyTarget=block` will lock out keyboard/mouse:
```
usbguard generate-policy --no-hashes > /etc/usbguard/rules.conf
```
**D-Bus API (system bus, bus name `org.usbguard1`):**
- `/org/usbguard1/Devices`, interface `org.usbguard.Devices1`: `listDevices(query s)→(a(us))`, `applyDevicePolicy(id u, target u, permanent b)→(rule_id u)`; signals `DevicePresenceChanged`, `DevicePolicyChanged`.
- `/org/usbguard1/Policy`, interface `org.usbguard.Policy1`: `listRules(query s)→(a(us))`, `appendRule(rule s, parent_id u, temporary b)→(id u)`, `removeRule(id u)`.
- Polkit-gated per action (`org.usbguard.Devices1.applyDevicePolicy`, etc.) — read actions (`listDevices`, `listRules`) can be granted freely, matching the read-only-by-default philosophy everywhere else in this spec.

Module UX: subscribe to presence/policy-change signals, surface a tray notification on unauthorized device insertion with Allow-once / Allow-permanent / Block actions calling `applyDevicePolicy` directly. `usbguard-simple-gui-py-qt` (Python 3 + PySide2 + D-Bus) is a useful reference implementation to study, not a dependency.

## Caveats

- **This is now a multi-month Rust project, not a weekend Python script.** The pivot from pass 1 (Python MVP) to pass 2 (Rust control plane) is a real increase in scope and build time, justified by this machine's specific incident history (privileged-code mistakes have already caused real outages here), but worth naming explicitly as a tradeoff. A pragmatic bridge: prototype the read-only dashboard in Python/GTK fast for feedback, but do not ship any write-action (fan control, USB authorize, service pause, log truncation) from that prototype — the real privileged daemon for those must be the Rust implementation before any write path goes live.
- **26.04.1's relevance to this machine specifically is limited** — since it's already installed and updated via `apt`, the point release only matters as a documentation/testing baseline, not as something to "upgrade to."
- **`hwctl` is mid-migration** from `.deb` to a strictly-confined snap around the 26.04.1/26.10 timeframe — don't hardcode a package-manager-specific integration path; check for either at runtime.
- **Glances' Ubuntu 26.04 package (4.3.3) has an unresolved CVE status ("Needs evaluation")** for a server-mode vulnerability fixed upstream in 4.5.3 — do not run it as an exposed network service if adopted as a reference/optional collector.
- **Fan control and USB blocking remain the two highest-consequence write actions** in this design — both must stay behind explicit polkit arming and the dead-man's-switch/lockout-prevention behavior described above, tested carefully before any default-on behavior is considered.
- **The USBGuard web documentation is known outdated** (upstream issue #566 flags the discrepancy) — verify the D-Bus interface signatures above against `busctl introspect org.usbguard1 /org/usbguard1/Devices` on the actual target machine before relying on them.
- **sudo-rs and rust-coreutils remain the defaults on 26.04** — prefer polkit/D-Bus over shelling out to `sudo` for privileged actions, and test any coreutils-flag-dependent scripting against rust-coreutils' actual flag support rather than assuming full GNU coreutils parity.