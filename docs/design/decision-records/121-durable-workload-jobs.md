# 121 — Durable workload jobs and explicit interruption review

Date: 2026-10-02
Status: accepted and implemented first increment; v0.2 queue75 remains partial.

Baseline now runs VM/LXC native actions in a worker and responds HTTP202 with a
persisted job ID. The authenticated Workload jobs page exposes actual reported
native command stages and outcomes, including after browser/service restart.
SQLite uses FULL synchronous writes; a process lease prevents two owners. A
request ID deduplicates matching submissions and refuses changed parameters.
One global workload mutation reservation protects shared VMID/template allocation;
this is conservative serialization, not a parallel per-resource scheduler.
Captured backend/storage context governs inspection even if defaults change.

On startup, unfinished jobs become interrupted, preserving the last observed
stage, with no automatic replay. Interrupted jobs block new workload mutations.
Read-only native inspection and exact-name acknowledgement are application
operations. Acknowledgement marks reviewed, never completed or repaired; it only
releases the reservation. Failed jobs can also be inspected/reviewed, but do not
hold the global reservation. Native lifecycle guards remain authoritative.
Nameless acquisition jobs currently require operator catalog inspection; generic
inspection does not prove their cache/template consistency.

Passwords are excluded from SQLite and public status, held only for one
authenticated POST retrieval. Restart discards unretrieved cleartext. Managed,
running, ready LXC containers now have a real Reset login action: fresh synthetic
password, native chpasswd through stdin, updated private hash metadata, no OS/data
reset. VM credential recovery remains open. No human guest account was added.
Provisioning stages the new modules. Existing drive/Operations job stores are
unchanged and remain outside this increment.

Verification: RED-before-GREEN tests were confirmed for the new behavior;
**2,874 guarded unit tests passed**, including fake native backends, actual local
HTTP requests, exclusive ownership, secret exclusion and stage preservation.
Actual Proxmox inside the approved disposable KVM clone also passed: Alpine
creation (CT126/base102), HTTP responsiveness, duplicate request refusal,
completed history after restart, one-time credential retrieval, actual LXC login
rotation with retained document, interrupted rebuild reservation, read-only
inspection, wrong-name refusal, acknowledgement, a fresh explicit native rebuild
retaining /home/job-proof, clean shutdown, and another restart retaining history.
See docs/verification/121. The interruption happened during rebuild preflight:
original stopped CT126 remained ready. **Mid-destruction recovery and host
power-loss recovery were not verified. No physical drive was written.** The
physical Proxmox backing device was serial-validated and explicitly read-only
under the writable disposable qcow2 overlay.

The clone's old transient service was absent and copied launcher non-executable;
these test-deployment issues were corrected inside the clone using a test service.
That is not proof of full production boot/provisioning (queue72). Named Baseline
volumes were observed mounted on the development host; production placement and
isolation through them were not exercised here.

Open queue75: native partial-phase/orphan repair and reconciliation, safe explicit
retry after destructive interruption, VM login recovery, durable old drive/jobs,
resource-specific concurrency and wider VM/backend interruption proofs. Backup,
app isolation and named distro installation remain rows59/60/74/73. DR120's
synchronous VM/LXC finding is superseded by this increment; its audit remains
history. INSTALL and handoff are corrected in place; DR117/118 artifacts remain
historical rather than being rehashed to pretend earlier verification used new code.
