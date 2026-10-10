# DR142: Turn unsupported runtime claims into errors and repair tasks

Date: 2026-10-04. Operator requested control of the project, an audit of fake or
mocked production behavior, explicit errors and tasks for missing functionality.
This increment is local, not deployed, merged or pushed. No physical devices or
operator credentials were handled. Tests use isolated stores, fake process
runners and local HTTP boundaries with the existing hardware guard active.

## Scope and decisions

Searched production libraries, entry points and boot scripts for simulation,
stub/fake/mock wording, constant success and failure-to-default fallbacks.
Traced affected metrics, diff/update, settings, firstboot, hardware, network,
handoff and backup-description call paths. Parsed 178 production Python files
for syntax. This is an initial audit, not an exhaustive proof that the entire
application is free of misleading claims.

The [active task register](../runtime-reality-tasks.md) lists REAL-001 through
REAL-012, the current error behavior, concrete repairs/acceptance criteria and
their links to existing queue rows. Production no longer claims successful
observations from failed pvesh/ethtool/package/hardware probes. Missing VM
measurements stay unknown, rather than zero. Error IDs reach settings callers
and firstboot logs. HTTP diff returns 503, CLI diff returns nonzero, and
selective updates refuse network apply when current settings cannot be read.

Handoff formerly ignored selected categories and restored the entire archive.
It now refuses any nonempty category selection before commands until a member
mapping exists. The generic backup/restore engine remains. iperf server start
submission remains real and bounded, but returns a failure describing partial
state because listener readiness is not verified. The submitted unit may run;
this failure must not be interpreted as proof of no side effects.

Network preference uses only observed gateways and checks each route mutation.
Failures do not save a preference; an unsuccessful re-add after route removal
reports partial state. A complete rollback transaction is still needed. Hardware
enumeration retains successful buses and reports failed ones on the page.
Firstboot's constant 'none staged' setup-intent assertion is now an explicit
unavailable inspection/unknown state. Legacy guest-backup description no longer
claims live/external disk recovery is established by a volume copy.

Test doubles and abstract interfaces remain where they test a real contract or
raise an explicit unimplemented exception. No production FakeRunner class/import
was found in this pass. AppData remains visibly a planner; its previews are not
removed or relabelled as runtime isolation. Existing real functionality must be
checked before declaring a capability missing.

## Corrections to DR141

DR141's claim that the live settings schema omitted `dhcp` was wrong: the
existing default schema already contained it. The extra-field implementation
was redundant and has been removed; positive/negative behavior tests remain.
Its ancestry walk also discarded cyclic or unidentified branches if a different
branch had a serial. New failing tests exposed both cases; the resolver now
supports only a bounded single parent chain and refuses branching/cycles.
Using lsblk `-d` keeps this lookup scoped to one node instead of descendants.
It does not prove multi-disk/ZFS ancestry or live Proxmox behavior. DR141 stays
as history; this record supersedes those inaccurate findings. INSTALL.md is
corrected in place and the work queue points to the new register.

## Verification and remaining work

New failure-injection cases were run RED before production changes, then GREEN.
They cover failed/malformed Proxmox inventory/history, unknown measurements,
failed/empty ethtool output, package-tool failure, HTTP errors, service-submission
readiness, selected restore refusal, boot cycles/unidentified branches, hardware
probe errors, guessed gateways, failed route demotion, error-ID propagation,
firstboot intent status and selective-update preservation.

The first wider run found downstream callers/fixtures requiring the changed
error contract: 45 failed, 3193 passed. Boot fixtures returned a physical disk
as its own parent; they now return no parent for that disk while keeping the
authorization/drive-swap assertions. Update success fixtures now contain actual
representative ethtool output, instead of successful empty output. Assertions
that failed observations were empty/disabled or that submission proved readiness
were replaced with error assertions because the operator requested that design
change. No required tests were removed or skipped.

Final guarded full unit suite: **3241 passed in 108.41 seconds**, no failures
or skips. Evidence: `docs/verification/142/full-suite-green.txt`; the earlier
wide-run failures remain in `first-wide-run.txt`. Deployment import closure:
`deployment-imports.txt`. `git diff --check`, `bash -n boot/provision.sh` and
AST syntax parsing of 178 production Python files passed.
Deployment import closure and production syntax checks pass. Runtime readiness,
selective restore mapping, full storage ancestry, complete network rollback,
application confinement and shipped installer/recovery remain open in the task
register; no full-project approval to main is implied by these tests.
