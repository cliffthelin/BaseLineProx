# DR167 — Authenticated update of the existing PC401 installation

2026-10-07. Continues DR146/DR158/DR165; does not supersede their boot evidence.

The operator selected PC401 serial <PC401 drive serial> and requested deployment
through the Installer. The existing source-preparation interface could capture
inputs but could not execute a current-source update of that installation.
Installer now offers a separate reviewed existing-installation update. This is
not the unfinished general new-install Build/Rebuild executor.

A completed operator-owned source-preparation job supplies the integrity-checked
snapshot. Current serial discovery and a completed whole-drive recovery snapshot
are required before issuing a fresh REDEPLOY challenge. The normal authenticated
web origin, CSRF, typed phrase, native credential verification and PolicyKit
executor remain in place. The agent never handles the operator's credentials.
The operation is a durable workload job, deduplicated against replay, with an
independently recorded deployment journal and an owner-bound recovery inspection.
Inspection identifies the currently attached serial and reads deployment history;
it explicitly does not establish boot or mount cleanup. Missing observations
prevent acknowledgment rather than manufacturing successful recovery.

The privileged helper uses a private mount namespace and per-serial lock. It
rejects mounted/open volumes, ambiguous PV/VG identity, incomplete roles, damaged
recovery/source inputs, unsafe target paths and foreign service-start policies.
Read-only root, independent-drive marker, SUBSTRATE policy, role UUIDs and fstab
are checked before read-write mounts. Captured source is deployed and actual
provisioning, initramfs and GRUB commands run in the target. No partitioning,
formatting, persistence restore, resize or credential generation occurs. Target
services are inhibited during offline provisioning. Ordinary cleanup failures
are errors; no force/lazy unmount is used. Success means deployment only.

Readiness additionally requires direct certificate-verified HTTPS and structural
verification of the active LAN-only nftables policy. An address/gateway alone
can no longer produce overall readiness. Repeat boots now enforce that firewall
even when firstboot was previously completed, without replaying installation.
The marker and corrupted-journal tests were updated for that explicit behavior
change; installation replay remains prohibited.

Confirmed failing tests preceded these implementations. Unit tests use fake
commands and synthetic disk identities; HTTP tests use actual local sockets
with test accounts/executors. They do not prove physical deployment. Final test
results are recorded in verification/167/RESULTS.md.

Read-only actual hardware observations found PC401 at /dev/sdc and PC601 at
/dev/sdb in this session; these names are observations, never persistent identity.
PC401 root and eight roles had no reported open LVs. The independent-drive marker,
role UUID fstab and resolver were read through debugfs. This is not boot proof.
PC401 still has the older 8 GiB BASELINE allocation; deploying code alone does
not implement the new 50 GiB storage profile or prove workload headroom.
PC601 was preserved. No physical writes or new QEMU/physical boot occurred.

The real Installer was reloaded with saved state and login HTTP200 checked.
Execution awaits interactive operator sign-in and fresh native confirmation.
Queue72/74/75/76/78 remain open for full stage execution, workload/application
coverage, storage capacity and physical boot/network/firewall/persistence proof.
Living INSTALL and SESSION_HANDOFF are updated; historical records are unchanged.
