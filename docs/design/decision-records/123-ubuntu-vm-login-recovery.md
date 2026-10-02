# 123 — Software-owned Ubuntu VM login recovery

Date: 2026-10-02
Status: implemented; actual guest reset/rebuild continuity verified in disposable KVM with the test network qualification below.

## Workflow

Running managed Ubuntu Desktop/Server environments on Proxmox now expose
**Reset login**. Explicit confirmation generates a fresh synthetic login for the
existing baseline-admin account; it does not create a human guest account, reset
OS or home, accept an operator's account password, or require an AI runtime.
The existing durable job/result API supplies cleartext once by authenticated POST;
job status/SQLite never receive it. Local-QEMU and arbitrary ISO/other-OS guests
remain explicitly unsupported for this operation, rather than claiming success.

Before generating a credential, the backend checks actual running registration,
recipe/profile consistency, mounted store paths, native directory-storage paths,
VM name/lock/root/home attachments, guest readiness markers, account UID and
actual mounted /home source. Native guest execution uses qm guest exec with
pass-stdin, synchronous waiting and a bounded timeout. Password hash goes to
chpasswd -e through stdin, never argv/env. Both CLI success and an actual guest
exited/exitcode=0 result are required; a returned PID, timeout, false exited flag,
nonzero/boolean exit code or signal cannot be reported as success.

The retained profile gets a flushed/fsynced, mode0600 applying journal before
changing the guest password. On successful native completion, the new hash
replaces the old profile hash and the journal is cleared atomically. Rebuild
refuses pending rotation, avoiding silent use of the old hash after an ambiguous
application result. A new confirmed Reset login resolves the pending rotation
using another fresh value. Unretrieved cleartext remains unrecoverable after
restart: rotate again. Pending rotation when a guest cannot become ready still
needs further recovery scope; there is no fake automatic recovery.

## Verification

**2,892 guarded unit tests passed in135.19s** (fake native runners, actual local
HTTP; not hardware evidence). Confirmed RED before GREEN for backend reset,
web entry point and redirected native storage. Tests prove single retrieval,
secret exclusion, retained home, regenerated seed using rotated hash, changed
name/home/lock refusal before credential generation, native unfinished/failed
results, pending-rotation rebuild refusal and a fresh successful retry.

**Actual disposable Proxmox-in-KVM**, docs/verification/123: existing Ubuntu
VM100 was started, its document read, login rotated via authenticated web action,
fresh password crypt-verified inside the actual guest, second retrieval lacked a
password, and document stayed unchanged. Explicit web rebuild completed. That
rebuild generated a normal seed without the old test-only proxy settings; under
the clone's restrict=on networking, the guest agent failed to become available.
This failure was not claimed as success. A fixture restored only the established
allowlisted package proxy and apt seed settings, changed the synthetic cloud-init
instance ID to rerun bootstrap, and booted the same already-rebuilt OS without
another OS reset or home initialization. The ready guest then retained the original
proxmox-retained-document and exactly the rotated profile hash. Final shutdown
and web restart retained the recorded outcome. The first test script also had an
incorrect proof-document filename; it was corrected before rotation, preserving
the existing running VM.

**No physical drive writes/deployment or ordinary-network firstboot proof.** The
approved running clone uses read-only physical backing plus writable qcow2. No
operator credentials handled; freshly generated test root login passed via stdin.
Native CLI reference: https://pve.proxmox.com/pve-docs/qm.1.html

## Remaining work and record continuity

Queue75 remains partial: incomplete allocation/template handling, running partial
clones, detach/orphan/in-flight task reconciliation, non-Ubuntu/other-backend VM
login recovery, old Drive/Operations job migration, concurrency and host power loss.
Retained-data backup/restore remains59/60, applied app lifecycle/isolation74,
full provision/ordinary-network/physical firstboot72, requested distro recipes73.
DR121/122's open VM login gap is narrowed, not retroactively rewritten. INSTALL,
queue, functional-audit follow-up and handoff are corrected in place; earlier
verification files remain historical. Test proxy bootstrap is a verification
fixture, not a claim that product network setup was implemented in this increment.
