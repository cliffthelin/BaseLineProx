# DR139: Production operations must not report simulated success

Date: 2026-10-03. Operator instruction: real operations only, with stubs
permitted in tests. This is an incremental production audit, not a claim that
every unfinished feature has been implemented or physically deployed.

## Changes

- Notification delivery now executes `notify-send` through the real runner.
  Returns true only on successful service acceptance and records the delivery
  result. Provisioning installs the real client (`libnotify-bin`). Missing
  session service is a failure, never log-only success.
- Removed 27 local fallback Runner classes. Required production imports now
  fail immediately when the execution dependency is absent. Removed the
  self-installer fallback that replaced missing installer modules with None.
  VM scripts no longer synthesize a CommandResult or missing-VM-ID helper when
  provisioning modules are absent; the scripts-inbox gate requires RealRunner.
  Injectable interface contracts remain; production entrypoints use their
  concrete real implementations. Test fakes remain under tests.
- Settings server now uses `SystemSectionApplier` and the existing config
  pipeline. A supported live operation must succeed before values are saved.
  Partial/failing operations are reported as failures with completed operations
  listed. Unknown fields and mismatched value types (including string booleans)
  refuse before commands. The storage-only adapter never claims live application.
- Rebuild request logging no longer returns `applied=True`. A log entry is an
  audit of a request, not proof of a reinstall; the real installer integration
  remains open. The settings route returns failure for this unfinished path.
- Firstboot firewall, tether, handoff and iperf3 configuration previously
  returned success without enforcing policy, configuring a link, restoring an
  archive or running a test/service. They now explicitly fail as unsupported
  transactions. These integrations are still missing, not completed fixes to
  the functionality itself.
- Network configuration supports a real hostname command only and refuses
  DHCP/link/unknown settings before any partial write. SSH reports failed
  service restart rather than ignoring its exit status.
- Cache update checking raises an explicit unavailable error instead of
  returning an empty list without consulting a source. Cache update application
  remains unavailable; manually reviewed pinned scripts retain their review
  requirement. The update CLI exits unsuccessfully for unavailable categories.

## Evidence and verification limits

RED failures confirmed log-only notification success, masked dependency
failure, saved/logged settings reported as applied, no-operation config success,
ignored SSH restart failure, incomplete DHCP handling, fabricated empty cache
checks and successful CLI exit for an unavailable category. Existing tests
asserting those old success results were changed to assert explicit failures;
no tests were deleted or skipped.

Actual local desktop delivery: real `notify-send` was accepted by the session
service. Its JSONL audit is saved under verification/139. The sandbox initially
blocked session D-Bus access; the explicitly approved real local command then
succeeded. This verifies a development desktop service, not physical Proxmox
deployment or the cage notification daemon. No physical drives or real account
credentials were touched, and no QEMU guest was used for these changes.

The settings, configuration and provisioning changes are tested against fakes
and real local subprocess/HTTP boundaries only, not applied to physical hardware.
Final full suite: **3165 passed in 112.54s**, no failures or skips. Deployment
import check, provision shell syntax and git diff whitespace check passed.
Evidence: `docs/verification/139/full-suite-green.txt`, `deployment-check.txt`,
`focused-green.txt`, `missing-runner-red.txt`, and `notification-real-desktop.jsonl`.
Current test evidence and remaining work are tracked in INSTALL and the v0.2
queue. No merge, commit or push was performed in this increment.

## Superseded claims and open work

Supersedes the GUI plan's log-only notification stub and the unconditional
success claims in the settings/rebuild and config-apply paths described above.
DR50/51 remain historical for the genuinely implemented smartd/ethtool paths;
any broader reading that every exported section is applied is incorrect.
Current GUI plan and INSTALL were corrected in place; historical decision
records are unchanged.

Queue rows72/75/76 still require installer stage orchestration, PARTUUID mounts,
fresh provisioning and firstboot execution. The separate configuration/rebuild/
cache integration gap is tracked by the DR139 queue entry. Runtime application
isolation (row74), requested system installations (row73), and physical proof
remain open. Catalog/planner validation and explicit unverified status are not
simulation, but neither is evidence that those runtime features are installed.
