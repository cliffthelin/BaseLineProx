# Guardian Phase 0 Contract Research
## Ubuntu 26.04.1 system control plane — pre-TDD research baseline

**Status:** Research complete enough to draft the Phase 0/1 TDD contract  
**Target platform:** Ubuntu 26.04.1 LTS (Resolute)  
**Purpose:** Freeze the contracts that would be expensive or dangerous to change after privileged implementation begins.

---

## 1. Executive conclusion

The Guardian architecture is ready to move from broad research into a Phase 0/1 TDD contract, with two implementation choices deliberately left as **Phase 0 decision gates** rather than guessed up front:

1. **Privilege topology:** prove the minimum viable privilege boundary for the long-running daemon and any privileged mechanism(s). Do not automatically assume a permanently unrestricted UID 0 process.
2. **StatusNotifierItem implementation:** test the three realistic implementations on Ubuntu GNOME 50 and Xfce 4.20 before selecting one.

Everything else needed to shape the control-plane contracts is sufficiently clear.

The governing architecture remains:

- Rust for the privileged/safety-critical boundary.
- Thin GUI/TUI/CLI/indicator clients over typed D-Bus APIs.
- Native service/library APIs first; kernel interfaces second; structured CLI third; scraped CLI last.
- Read-only by default.
- Explicit risk levels for every write operation.
- No generic privileged shell-command endpoint.
- Every risky action follows:
  **Snapshot → Validate → Authorize → Apply → Observe → Confirm → Commit or Rollback.**
- Correlation and evidence chains are more important than isolated metrics.
- The system must reduce diagnostic cost when the host is already under pressure.

---

## 2. Ubuntu 26.04.1 contract baseline

Versions below are the Ubuntu Resolute versions researched for contract compatibility. Patch revisions can advance during the LTS lifetime; Guardian must capability-detect instead of assuming an exact patch forever.

| Component | Researched Resolute version | Guardian role |
|---|---:|---|
| systemd | 259.5 (current Resolute updates at research time) | service lifecycle, cgroups, boot, logind, transient units |
| D-Bus | 1.16.2 | IPC boundary |
| polkit | 127 | authorization |
| NetworkManager | 1.54.3 | network state + native checkpoint/rollback model |
| UDisks2 | 2.10.91 | storage topology and user-facing safe operations |
| AccountsService | 23.13.9 | next-login desktop/session selection |
| UPower | 1.91.1 | battery/UPS/power-device telemetry |
| power-profiles-daemon | 0.30 | platform power-profile provider |
| thermald | 2.5.11 | CPU/platform thermal ownership |
| fwupd | 2.1.1 | firmware provider |
| bolt | 0.9.10 | Thunderbolt authorization/state |
| logrotate | 3.22 | external flat-log rotation |
| libayatana-appindicator-glib | 2.0.1 | candidate tray implementation, compatibility not yet proven |
| python3-dbusmock | 0.38.1 | test-only D-Bus mocking |
| umockdev | 0.19.7 | test-only hardware/udev mocking |
| Rust compiler | 1.93.1 packaged as `rustc` at research time | build toolchain baseline |
| Ubuntu-packaged zbus source | 5.13.2 | available distro D-Bus Rust library baseline |
| upstream zbus docs reviewed | 5.19.0 | current typed proxy/interface design reference |
| ksni | 0.3.6 | candidate direct Rust SNI + DBusMenu implementation |

### Contract rule

Guardian tests **capabilities and API presence**, not only package versions. Version numbers are recorded for reproducibility, but provider adapters must fail closed or degrade gracefully when an expected member is absent.

---

## 3. Authoritative-source hierarchy

For every system provider, contract research and generated bindings should use sources in this order:

1. **Introspection XML / polkit policy / service files installed by the exact Ubuntu package**
2. Ubuntu package source for the installed version
3. Upstream source tagged to the matching version
4. Upstream current reference documentation
5. Generic web documentation, blog posts, examples

This is especially important for services whose online docs have drifted from their packaged D-Bus interface (USBGuard is already a known example).

Guardian should capture provider provenance:

```text
provider_id
package_name
package_version
interface_name
interface_version
introspection_hash
policy_hash
observed_at
```

This allows regression tests to detect when an Ubuntu update changes an external contract.

---

## 4. D-Bus service contract

### 4.1 Packaging/layout

Ubuntu's D-Bus documentation recommends packaged system-service defaults under:

```text
/usr/share/dbus-1/system.d/
/usr/share/dbus-1/system-services/
```

with administrator overrides under:

```text
/etc/dbus-1/system.d/
```

A Guardian package should therefore not write vendor defaults directly into `/etc/dbus-1/system.d/`.

A systemd-activated D-Bus service can use:

```ini
[D-BUS Service]
Name=<guardian well-known name>
SystemdService=<guardian systemd unit>
```

and a matching systemd unit with:

```ini
[Service]
Type=dbus
BusName=<guardian well-known name>
```

Guardian can still be boot-started before login while retaining D-Bus activation as a recovery/start-on-demand path.

### 4.2 D-Bus policy philosophy

The bus policy should be deliberately simple:

- allow clients to send method calls to Guardian,
- authenticate/authorize semantics inside the Guardian mechanism,
- use polkit for domain-specific authorization.

Do **not** attempt to encode concepts such as "this user may power off removable but not system storage" in D-Bus XML policy.

### 4.3 Interface versioning

Do not freeze the public bus name until the final project namespace/reverse-domain is selected.

Once selected:

- public interfaces MUST carry a major version suffix from their first release (`...Control1`, `...Storage1`, etc.);
- additive compatible changes remain in the same major version;
- breaking method/signature/semantic changes require a new interface major;
- object paths must be stable and documented;
- clients must not infer provider capabilities merely from package version.

A possible shape, **not yet the final namespace**, is:

```text
<namespace>.Guardian1
/<namespace path>/Guardian1
    /Capabilities
    /Transactions
    /Incidents
    /Storage
    /Diagnostics
```

### 4.4 Rust D-Bus implementation

`zbus` is a strong default for Phase 1:

- `#[proxy]` produces typed client proxies;
- `#[interface]` exports typed server interfaces;
- generated interfaces support D-Bus introspection;
- signals and property changes can be represented with typed streams.

**Contract requirement:** external provider adapters should use typed proxies. Avoid free-form method names and `Variant` blobs where a stable typed representation can be defined.

### 4.5 No generic root command

The system D-Bus API MUST NOT expose:

```text
RunCommand(string)
RunShell(string)
Execute(argv supplied by arbitrary client)
```

Privileged methods must be typed, bounded operations, e.g.:

```text
PowerOffDrive(drive_id)
SetDefaultSession(session_id)
PauseService(unit)
SetTransientResourceLimit(scope, limit)
ApplyLogPolicy(policy_id)
```

The implementation may internally execute a provider CLI only when no stronger API exists, but the caller never receives a general-purpose root execution primitive.

---

## 5. polkit authorization contract

### 5.1 Caller identity

The UI/TUI/CLI is untrusted input.

When a client calls Guardian over the **system bus**, Guardian must authorize the **actual D-Bus caller identity**. The preferred authorization subject for this IPC model is the caller's unique `system-bus-name`, rather than trusting a UID/PID sent in method arguments.

Never accept authorization identity fields such as:

```text
requested_uid
requested_username
caller_pid
is_admin=true
```

from the client as proof.

### 5.2 Interactive authorization

Only an explicit human action may set the equivalent of polkit's `AllowUserInteraction`.

Therefore:

- clicking "Power off this drive" may open an auth challenge;
- a TUI action chosen by the user may open text authentication;
- background monitoring must not unexpectedly open auth prompts;
- automatic Protect-mode actions must be pre-authorized by policy or not execute.

### 5.3 TUI/recovery authentication

Polkit supports a textual authentication agent (`pkttyagent`), including binding to a process/system-bus name.

Phase 0 must test:

| Client context | Required behavior |
|---|---|
| GNOME GUI | graphical polkit challenge |
| Xfce GUI | graphical polkit challenge |
| ordinary VT TUI | text challenge succeeds |
| Guardian recovery target | explicit text-auth policy works |
| SSH | policy intentionally defined; never accidental inheritance |

### 5.4 Polkit action granularity

Actions should correspond to meaningful risk units, not one universal `admin` action.

Examples:

```text
<namespace>.guardian.storage.power-off
<namespace>.guardian.storage.force-unmount
<namespace>.guardian.service.pause
<namespace>.guardian.session.set-default
<namespace>.guardian.logs.configure
<namespace>.guardian.resources.throttle
<namespace>.guardian.usb.authorize
<namespace>.guardian.recovery.advanced
```

High/very-high recovery actions must never silently inherit permission from a low-risk action.

---

## 6. Privilege topology and systemd sandbox

### 6.1 What research established

systemd explicitly provides controls appropriate for hardening a long-running Guardian service:

- `ProtectSystem=strict`
- `ProtectHome=`
- `NoNewPrivileges=`
- `CapabilityBoundingSet=`
- `ProtectKernelModules=`
- `ProtectKernelTunables=`
- `ProtectControlGroups=`
- `PrivateTmp=`
- `PrivateDevices=` where compatible
- explicit `ReadWritePaths=`, `StateDirectory=`, `LogsDirectory=`

`systemd-analyze security` can score many of these exposure dimensions.

### 6.2 What must NOT be prematurely frozen

Do not yet assume either extreme:

- "the whole daemon must permanently run as unrestricted root", or
- "everything can definitely run as an unprivileged account."

Several Guardian operations can already be read without root or delegated to existing system services, while some configuration/recovery operations may require stronger privilege.

### 6.3 Phase 0 privilege decision gate

Build two minimal prototypes and measure what actually needs privilege:

**Prototype A — hardened privileged daemon**

- Rust
- `Type=dbus`
- strongly restricted filesystem paths/capability set
- no network unless a provider explicitly requires it
- typed actions only
- polkit authorizes caller

**Prototype B — unprivileged core + narrow privileged mechanism**

- long-running correlation/monitoring daemon runs as dedicated system user
- a smaller privileged D-Bus mechanism performs only typed write/recovery operations
- mechanism can be D-Bus/systemd activated on demand
- transaction identity and audit relationship remain preserved

Select the model with the least privilege that still keeps transactions reliable and comprehensible.

### 6.4 Required gate

No write-capable Phase 1 service may ship until:

```text
systemd-analyze security <unit>
```

has been reviewed and every intentionally disabled hardening control is documented with a reason.

---

## 7. Capability Registry contract

A Capability Registry entry should be richer than "package installed".

Minimum schema:

```text
capability_id
provider_id
provider_version
availability
health
read_support
write_support
authorization_mode
boot_availability
interface_kind
interface_name
interface_hash
diagnostic_cost
last_observed_at
```

`availability` should distinguish at least:

```text
AVAILABLE
DEGRADED
UNAVAILABLE
UNSUPPORTED
UNKNOWN
```

A provider failure must not become a false "healthy" state.

---

## 8. Provider Arbitrator contract

The Provider Arbitrator is a **Phase 1 architectural requirement**, not a later enhancement.

Its role is separate from discovery:

> Registry: what can do this?  
> Arbitrator: who currently owns this, and may Guardian change it?

Minimum arbitration record:

```text
capability_id
candidate_providers[]
authoritative_provider
current_owner
ownership_basis
conflicts[]
write_permitted
rollback_kind
risk_class
decision_reason
```

`rollback_kind`:

```text
NATIVE
EMULATED
BEST_EFFORT
NONE
```

### Single-writer invariant

For a mutable capability, Guardian must not write when another provider is authoritative unless:

1. the provider explicitly exposes Guardian-compatible control, or
2. ownership is intentionally transferred as a transaction with rollback.

Examples:

- `thermald` owns CPU thermal policy → Guardian observes.
- power-profiles-daemon owns platform profile → use its API, don't write low-level policy independently.
- CoolerControl owns a PWM channel → Guardian should not simultaneously manipulate the raw PWM interface.
- NetworkManager owns configured network state → use NetworkManager, not hand-written files behind it.

---

## 9. Transaction engine contract

NetworkManager's checkpoint API validates the Guardian safety model:

- snapshot selected state;
- apply changes;
- auto-rollback after a timeout if not committed;
- explicit commit removes checkpoint;
- rollback has structured per-device results.

Guardian should generalize these semantics without pretending every provider offers a native checkpoint.

### 9.1 Transaction state machine

Recommended minimum:

```text
CREATED
VALIDATING
VALIDATED
AUTHORIZING
AUTHORIZED
APPLYING
OBSERVING
COMMITTED

ROLLING_BACK
ROLLED_BACK

REJECTED
FAILED
ROLLBACK_FAILED
EXPIRED
CANCELLED
```

Terminal states are immutable.

### 9.2 Transaction record

```text
transaction_id
idempotency_key
action_type
risk_class
initiating_bus_name
initiating_session
provider_id
capability_id

created_at
deadline

pre_state
validation_results
arbitration_result
authorization_result

requested_change
provider_request
provider_response

observation_policy
observations

commit_result
rollback_result

incident_ids[]
```

### 9.3 Transaction invariants

- Every write has a transaction ID.
- Validation occurs again at the privileged boundary immediately before apply.
- Stale preconditions fail closed.
- Native provider checkpointing is preferred when available.
- If rollback is impossible, the UI must say so **before** authorization.
- High/very-high risk actions cannot pretend to be reversible.
- Provider timeouts are bounded.
- Cancellation semantics are explicit.
- Repeated client retries use an idempotency key to avoid double execution.
- The audit record survives client crashes.

---

## 10. UDisks storage-provider findings

UDisks confirms several important I/O Guardian contracts.

### 10.1 Drive vs block-device identity

Guardian must not model storage as just `/dev/sdX`.

Represent at least:

```text
physical/topological device
UDisks Drive
block device
partition
filesystem
mount
```

and preserve links between them.

### 10.2 `PowerOff()` safety

UDisks documents that `PowerOff()`:

- attempts to ensure no process is using the drive,
- commits in-flight buffers/caches,
- for USB deconfigures the USB device and disables the upstream hub port,
- is only available when `CanPowerOff == true`.

### 10.3 Sibling impact

Some physical USB devices/enclosures expose multiple drives. UDisks provides `SiblingId` for this.

Guardian therefore MUST:

- evaluate `CanPowerOff`,
- discover siblings,
- show all potentially affected siblings before authorization,
- never label a UDisks power-off as "safe isolate only this logical disk" when siblings may be affected.

### 10.4 User-initiated only

UDisks explicitly warns that `PowerOff()` should only be called in response to a user action because guarantees are limited.

Therefore:

> UDisks `PowerOff()` is **not** eligible for unattended Guardian Protect-mode automation.

It remains a Moderate recovery action offered to the user.

---

## 11. Device identity and udev contract

Guardian must avoid treating volatile names such as `/dev/sdb` as persistent identity.

Model distinct identity dimensions:

```text
current kernel/sysfs path       -> topology now
udev physical path / port path  -> connection location
serial/WWN where available      -> hardware identity
filesystem UUID                 -> filesystem identity
UDisks object path              -> provider object identity for current boot
```

These identifiers are **not interchangeable**.

A physical USB enclosure may change block names while remaining the same physical device; a filesystem can move to a different physical device; a port path identifies connection topology, not necessarily the medium.

Phase 0 fixtures should explicitly test these distinctions.

---

## 12. AccountsService/session-switching findings

AccountsService 23.13.9 documents:

- `SetSession()` for graphical sessions;
- deprecated `SetXSession()`, superseded because not every graphical session uses X.

### Contract correction to merged spec

Guardian should:

1. enumerate valid installed session definitions from the platform;
2. validate a requested session against those definitions;
3. use AccountsService `SetSession()` as the primary provider action;
4. use legacy `.dmrc` / `SetXSession()` only through a compatibility adapter proven necessary on that target display-manager configuration;
5. never write multiple state stores unconditionally "just in case."

The client must never be allowed to pass an arbitrary unvalidated session string directly to a privileged write.

---

## 13. UPower provider contract

UPower supplies a stable system-bus provider:

```text
org.freedesktop.UPower
/org/freedesktop/UPower
```

Key methods include:

- `EnumerateDevices()`
- `GetDisplayDevice()`

Guardian Phase 1 can use UPower as a read-only source for batteries, line power, and supported UPS/power devices.

Do not scrape `upower -d` when the D-Bus API is available.

---

## 14. Power-profiles-daemon and provider ownership

Power-profiles-daemon exposes `org.freedesktop.UPower.PowerProfiles` and contains information directly useful to the Provider Arbitrator.

Important properties/features:

- `ActiveProfile`
- `Profiles`
- each profile can identify a `Driver`
- `PerformanceDegraded`
- `Actions`
- `ActiveProfileHolds`
- profile holds have ApplicationId, Profile, and Reason

It also exposes `HoldProfile()`/release behavior for temporary use.

### Guardian contract

The dashboard should be able to answer:

```text
Active profile: balanced
Provider/driver: <reported driver>
Held by: <applications and reasons>
Performance degraded: <reported reason>
```

Guardian must not blindly overwrite a held or provider-owned profile.

If a profile change is requested, it is a transaction through the authoritative provider.

---

## 15. Thermal ownership contract

Full thermald/fan-control implementation is deferred, but Phase 1 needs a provider ownership model now.

At Phase 1:

- detect whether thermald is installed/running;
- treat it as a candidate/authoritative thermal-policy provider where applicable;
- read temperatures from authoritative read interfaces;
- do not implement raw PWM writes yet;
- expose ownership conflicts in the registry/arbitrator.

Detailed fan control, CoolerControl, LACT, EC/BIOS ownership, and vendor thresholds belong to the Thermal & Power implementation phase.

---

## 16. PSI and Diagnostic Budget

Linux PSI is strong enough to be a first-class event source rather than just a dashboard metric.

System-level files:

```text
/proc/pressure/cpu
/proc/pressure/memory
/proc/pressure/io
```

The kernel supports pressure triggers:

```text
<some|full> <stall_us> <window_us>
```

registered on a file descriptor and waited on with `select()`, `poll()`, or `epoll()`.

Kernel-documented trigger windows range from 500 ms to 10 seconds; unprivileged monitors have an additional window constraint intended to limit resource use.

### Contract

Guardian should support both:

1. sampled trend telemetry (`avg10`, `avg60`, `avg300`, `total`);
2. event-driven PSI threshold subscriptions for escalation.

### Diagnostic Budget classes

```text
NEGLIGIBLE
LOW
MODERATE
HIGH
```

Each diagnostic provider declares cost dimensions such as:

```text
cpu_cost
memory_cost
io_read_cost
io_write_cost
kernel_trace_cost
expected_duration
```

The budget manager can veto escalation.

Examples:

- critical I/O pressure → do not start disk-write-heavy tracing;
- critical memory pressure → prohibit large diagnostic buffers;
- root filesystem low → use in-memory ring buffer and suppress optional persistence;
- thermal emergency → prioritize remediation/observation over expensive profiling.

### Core safety invariant

**Guardian must not materially worsen the resource class it is trying to diagnose.**

---

## 17. systemd resource-control contract

systemd 259's cgroup-v2 controls validate "throttle before kill".

Important semantics:

- `MemoryHigh=` is the primary memory-throttling mechanism;
- `MemoryMax=` is a hard last line of defense that can invoke OOM behavior;
- `IOWeight=` apportions relative I/O bandwidth;
- per-device I/O limits exist;
- transient units/scopes can make interventions temporary instead of editing permanent unit files.

### Contract rules

- Use soft/throttling controls before hard ceilings where the goal is stabilization.
- Prefer transient runtime scopes/changes for incident mitigation.
- Permanent unit-file changes are a separate higher-risk action.
- Every throttle action has a time-to-live or explicit revert path unless the user requests persistence.
- Never apply block-device limits using a partition when the provider requires the originating physical device.

---

## 18. systemd-logind "System Blockers" provider

Guardian can expose current suspend/shutdown blockers from logind's inhibitor model.

`ListInhibitors()` returns information including:

```text
what
who
why
mode
uid
pid
```

The inhibitor model distinguishes operations such as:

- sleep
- shutdown
- idle
- power/suspend/hibernate key handling
- lid switch

and supports block/delay-style behavior.

### Phase 1 value

This is a strong read-only provider for:

> "Why won't my machine suspend/reboot/shut down?"

It can be added without granting Guardian extra write capability.

Do not attempt to create login sessions directly; session construction belongs to PAM/logind integration.

---

## 19. Logging/audit persistence research

### 19.1 journald behavior

journald already enforces individual journal-file size limits synchronously. It also supports global usage/free-space limits.

Important nuance:

- `SystemMaxUse` limits journal usage;
- `SystemKeepFree` sets space journald should leave free;
- journald respects the smaller effective limit;
- if **other** software later fills the filesystem, journald stops growing but does not necessarily delete enough existing history to magically restore the configured free-space floor.

This preserves the value of Guardian's filesystem-level capacity watcher and "time to exhaustion" forecast.

### 19.2 Guardian logging layers

Do not use the journal itself as the sole transaction database.

Recommended split:

**Operational log**
- journald
- ordinary service diagnostics
- rate/size governed by systemd

**Transaction/incident metadata**
- structured local state under `/var/lib/guardian`
- bounded and versioned
- survives GUI/client crashes
- schema designed for querying and audit

**Flight recorder**
- bounded memory ring buffer
- small quota-capped local spill area if necessary
- never placed on monitored removable storage

### 19.3 External flat files

The CUPS-style per-path watchdog remains relevant for logs not controlled by journald.

Default response remains `alert_only`, with stronger actions explicitly authorized.

Emergency action preference:

1. application-native log control,
2. existing journal/rotation policy,
3. detect growth and forecast exhaustion,
4. pause/throttle culprit when safe,
5. rotate,
6. truncate only when explicitly configured as emergency behavior.

---

## 20. Indicator research — decision must be tested, not guessed

This pass found a meaningful compatibility conflict.

### Candidate A — legacy GTK3 AyatanaAppIndicator

Pros:
- proven Ubuntu GNOME AppIndicator behavior;
- traditional `com.canonical.dbusmenu`.

Cons:
- old GTK-based implementation is considered obsolete upstream;
- introduces GTK3 specifically for a tiny indicator.

### Candidate B — new GLib-only Ayatana AppIndicator 2.0.1

Pros:
- packaged in Ubuntu 26.04;
- upstream-preferred replacement;
- no GTK3 dependency.

Concern:
- the new implementation moved menus away from the older DBusMenu transport to GTK menu/action D-Bus protocols;
- an upstream compatibility issue and GNOME developer report indicate current GNOME AppIndicator hosts may not understand the new menu protocol correctly.

Therefore it MUST NOT be frozen as the default solely because it is newer.

### Candidate C — direct Rust SNI + canonical DBusMenu

`ksni` 0.3.6 is a strong candidate:

- Rust;
- implements the KDE/freedesktop StatusNotifierItem model;
- documents GNOME use with AppIndicator extension;
- supports `com.canonical.dbusmenu`;
- uses zbus;
- test suite uses isolated `dbus-run-session`.

### Phase 0 compatibility spike

Test all relevant candidates on:

| Environment | Required |
|---|---|
| Ubuntu 26.04.1 GNOME 50 / Wayland | yes |
| Xfce 4.20 panel Status Tray | yes |

Acceptance criteria:

- icon appears after login;
- menu appears;
- state/icon changes propagate;
- no duplicate/stolen indicator;
- clean reconnect after panel/Shell restart or user logout/login;
- no X11 dependency;
- daemon absence shows degraded/offline state rather than hanging UI;
- accessible labels/tooltips where host supports them.

**Current recommendation:** expect Candidate C (`ksni`) to win, but do not freeze it before the compatibility test.

---

## 21. Fault-simulation/testing stack

Ubuntu 26.04 already contains excellent test tooling for this architecture.

`power-profiles-daemon` itself build-depends on:

- `python3-dbusmock`
- `umockdev`

which is good prior art for using them to test a D-Bus + hardware-facing service.

### Test Layer 1 — pure Rust

No system bus or real hardware.

Test:

- schemas;
- transaction state machine;
- risk ordering;
- provider arbitration;
- capability merging;
- idempotency;
- timeout logic;
- Log Lens normalization;
- incident correlation;
- diagnostic-budget decisions.

### Test Layer 2 — isolated D-Bus integration

Use private buses / `dbus-run-session` and D-Bus mocks.

Mock:

- provider absent/present;
- interface member missing;
- delayed response;
- provider disconnect mid-call;
- malformed/unsupported property;
- signal storms;
- authorization denied/challenge;
- stale provider object;
- owner change on bus.

### Test Layer 3 — mocked hardware/udev

Use `umockdev` and fixtures.

Test:

- hotplug;
- removal during operation;
- changed `/dev/sdX` name;
- same device on different port;
- multiple logical drives sharing a physical parent;
- absent serial/WWN;
- malformed sensor value;
- sensor disappearing;
- device property changes.

### Test Layer 4 — disposable Ubuntu 26.04.1 VM

Required before any destructive provider is considered complete.

Test real:

- system D-Bus;
- polkit GUI/TUI authentication;
- systemd transient units;
- cgroup resource controls;
- real AccountsService behavior;
- UDisks with loop/removable-like devices where safe;
- full-filesystem scenarios on a small disposable filesystem;
- crash-looping test services;
- Guardian service sandbox;
- GNOME/Xfce indicator behavior.

### Fault cases to include early

```text
crash-loop service
log grows until tiny test filesystem nearly full
provider disappears halfway through transaction
timeout after apply but before observation
rollback fails
duplicate client retry
PSI alert while diagnostic budget is already constrained
storage object removed between validation and apply
session request for nonexistent session
client dies during polkit/transaction
daemon restart with transaction in nonterminal state
```

---

## 22. Provider-adapter interface — recommended Phase 0 shape

The exact Rust trait syntax may evolve, but the contract should express:

```text
Provider
  identity()
  version()
  probe()
  capabilities()
  health()
  subscribe_events()

Capability-specific adapter
  inspect()
  validate(action)
  snapshot(action)
  apply(action)
  observe(expectation)
  rollback(snapshot)
```

Not every provider supports every method.

The adapter must explicitly report unsupported behavior instead of supplying a fake success.

Example:

```text
rollback = NONE
```

is valid and must be shown to the user before authorization.

---

## 23. Error model

D-Bus errors should be typed and stable.

Suggested categories:

```text
NotAuthorized
AuthenticationUnavailable
Unsupported
ProviderUnavailable
ProviderChanged
PreconditionFailed
Conflict
Busy
TimedOut
Cancelled
InvalidRequest
Unsafe
ApplyFailed
ObservationFailed
RollbackFailed
PersistenceFailed
Internal
```

Machine-readable details belong in structured result data where appropriate; error strings remain human-readable diagnostics, not the only contract.

Never expose raw provider stack traces or arbitrary command output as the stable API.

---

## 24. Event and incident contracts

### Event

A normalized immutable observation:

```text
event_id
timestamp_monotonic
timestamp_wall
source_provider
event_type
resource_refs[]
severity
normalized_key
raw_reference
attributes
```

### Incident

A correlation envelope:

```text
incident_id
opened_at
closed_at
status
summary
confidence
primary_resource
event_ids[]
evidence[]
candidate_causes[]
recommended_actions[]
transaction_ids[]
outcome
```

Raw evidence remains separately retrievable where policy permits.

Log Lens deduplication affects **presentation/correlation**, not deletion of authoritative journal data.

---

## 25. Boot availability levels

Every provider should declare when it can exist:

```text
EARLY_BOOT
SYSTEM_BUS
PRE_LOGIN
USER_SESSION
DESKTOP_ONLY
OPTIONAL
```

Examples:

- PSI: early/system
- systemd: early/system
- UDisks: system bus
- AccountsService: system bus
- GUI polkit agent: user session
- SNI host: desktop only

This prevents a recovery TUI from trying to depend on a desktop-only provider.

---

## 26. Phase 0 contract gates

The Phase 0/1 TDD plan should not permit implementation to progress past each gate until tests prove it.

### G0 — API contract
- D-Bus naming/versioning selected.
- typed errors defined.
- no generic command API.
- introspection snapshot tests pass.

### G1 — identity/auth
- unique system-bus caller identity is used for authorization.
- GUI auth works.
- VT text auth works.
- background action cannot cause unexpected auth prompt.

### G2 — privilege
- chosen privilege topology documented.
- systemd sandbox tested.
- `systemd-analyze security` reviewed.
- explicit filesystem/capability needs recorded.

### G3 — transaction safety
- state machine tests pass.
- idempotent retry works.
- timeout/rollback behavior proven.
- restart recovery for incomplete transaction tested.

### G4 — provider arbitration
- conflicting owners cannot both write.
- unavailable provider degrades cleanly.
- authoritative-provider reason is explainable.

### G5 — diagnostic budget
- high-cost collector can be vetoed under matching pressure.
- recorder remains available when persistence is restricted.

### G6 — storage safety
- UDisks `CanPowerOff` enforced.
- sibling impact shown.
- stale/removing device causes fail-closed behavior.

### G7 — session safety
- only enumerated valid sessions accepted.
- AccountsService `SetSession` used on supported target.
- compatibility fallback is target-specific.

### G8 — indicator
- one implementation passes GNOME 50 and Xfce 4.20 compatibility matrix.

### G9 — package/update drift
- external introspection/provider fixture changes are detectable in CI or package-baseline tests.

---

## 27. Documentation packages worth installing in the development VM

These are useful because they track Ubuntu's packaged versions:

```bash
sudo apt install \
  policykit-1-doc \
  udisks2-doc \
  libaccountsservice-doc \
  upower-doc \
  fwupd-doc \
  libayatana-appindicator-glib-doc
```

Also retain local copies/hashes of installed provider artifacts where present:

```text
/usr/share/dbus-1/interfaces/
/usr/share/dbus-1/system-services/
/usr/share/dbus-1/system.d/
/usr/share/polkit-1/actions/
```

Do **not** modify these vendor files for Guardian research; copy/read them.

---

## 28. Research deferred until provider phases

The following do **not** need to delay Phase 0/1:

- SMART attribute semantics across vendors
- NVMe vendor-specific telemetry
- NVML detailed throttle/control implementation
- fan-control/PWM ownership specifics
- CoolerControl integration
- LACT integration
- advanced thermald tuning
- PCP history backend
- Netdata integration
- atop capture policy
- KernelShark/trace-cmd deep workflows
- detailed AppArmor profile authoring
- kdump internals
- Dracut recovery-module authoring
- USBGuard write/API implementation beyond preserving the known interface-verification requirement
- advanced BPF probes

Each is a later provider/module research task.

---

## 29. Corrections/additions to fold into the merged Guardian spec

Before the Phase 0/1 TDD contract, update the governing spec with these changes:

1. Add **Provider Arbitrator** beside Capability Registry.
2. Add **Diagnostic Budget Manager** as a first-class subsystem.
3. Add **Phase 0 — Contracts & Simulator**.
4. Refine AccountsService behavior to prefer `SetSession()`; use `.dmrc`/`SetXSession` only as discovered compatibility fallback.
5. Replace "new GLib Ayatana is the default" with an **indicator compatibility decision gate**. Direct Rust `ksni` is currently the leading candidate.
6. State that Guardian's long-running privilege topology is a Phase 0 least-privilege gate, although all privileged code remains Rust.
7. Require authorization based on the real D-Bus caller identity.
8. Require no interactive auth from background automation.
9. Require UDisks sibling/`CanPowerOff` validation and user initiation.
10. Make PSI event triggers part of the Diagnostic Budget/event engine.
11. Add the `systemd-logind` inhibitor provider for "System Blockers."
12. Add provider/interface provenance and contract-drift detection.
13. Specify typed D-Bus errors and transaction idempotency.
14. Require systemd service-hardening review before enabling writes.

---

## 30. Final research decision

**GO to Phase 0/1 TDD contract.**

There is no remaining broad research topic that should block drafting the contract.

The two unresolved design choices are now sufficiently bounded to become test-driven Phase 0 decisions:

- exact privilege split;
- exact SNI/indicator implementation.

That is preferable to doing more speculative research because both depend on behavior that can be conclusively tested on the actual Ubuntu 26.04.1 GNOME/Xfce target.

The contract should now convert this research into:

1. immutable architecture rules,
2. failing acceptance tests,
3. provider mocks/fixtures,
4. decision gates,
5. implementation order.

---

# Source register

Primary references used in this research pass:

- Ubuntu Resolute package archive — package/version and documentation package records
- Ubuntu `dbus-daemon(1)` manual — system-service policy and activation layout
- Ubuntu polkit 127 manuals (`polkit(8)`, `polkitd(8)`, `pkttyagent(1)`)
- Ubuntu systemd resource-control and execution-environment manuals
- Linux kernel Pressure Stall Information documentation
- UDisks2 current D-Bus reference manual (`org.freedesktop.UDisks2.Drive`)
- AccountsService 23.13.9 API reference
- UPower D-Bus reference
- power-profiles-daemon D-Bus reference
- NetworkManager D-Bus checkpoint API
- zbus 5 API documentation
- ksni 0.3.6 documentation/source
- Ubuntu power-profiles-daemon source-package build dependencies (dbusmock + umockdev prior art)

## Key source URLs

- https://packages.ubuntu.com/
- https://manpages.ubuntu.com/manpages/resolute/man1/dbus-daemon.1.html
- https://manpages.ubuntu.com/manpages/resolute/man8/polkit.8.html
- https://manpages.ubuntu.com/manpages/resolute/man8/polkitd.8.html
- https://manpages.ubuntu.com/manpages/resolute/man5/systemd.resource-control.5.html
- https://manpages.ubuntu.com/manpages/resolute/man5/journald.conf.5.html
- https://cdn.kernel.org/doc/html/latest/accounting/psi.html
- https://storaged.org/doc/udisks2-api/latest/gdbus-org.freedesktop.UDisks2.Drive.html
- https://upower.freedesktop.org/docs/UPower/
- https://docs.rs/zbus/
- https://docs.rs/ksni/
