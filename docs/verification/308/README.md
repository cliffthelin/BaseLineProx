# PC601 solutions incorporated into the PC401 test candidate

2026-10-15. Branch `codex/pc401-parity`. Code candidate: `ea3a658`.
Claude source imported through `b0fd445`; merge `5506b21`. PC401 installer
UUID remains `5029a80d-c748-4616-aa08-99ac560f5311`.

## Evidence assessment

| Area | Evidence available | PC401 conclusion |
| --- | --- | --- |
| PC601 installed browser/startup | Shared `pc601-install14.log` ends with browser checkpoint, QEMU exit 0 and `done: install, firstboot, kiosk` | Historical physical-target KVM install success; no new native boot observed here |
| NIC negotiation, VG naming, USB quirks, UUID mounts, browser retry | Imported in the earlier PC401 merge and retained | Source present; physical PC401 still needs deployment and acceptance |
| New web pages, launcher, vault, layered settings | Newer than the installed PC601 log; DR259 explicitly says unrehearsed | Imported, with fresh QEMU library/HTTP checks below; not treated as PC601-installed successes |
| Five host diagnostic tools | PC601 source records installation; newer cache contains 403 packages | Tools page runs; this live guest does not prove all tools installed on PC401 |
| Guest OS/application configuration | Catalogue and layers exist | Guest-side settings appliers and default installed applications remain incomplete |
| Proxmox state on USER_ADMIN | Drop-in/service ordering exists; source routing defect below | Not ready for installed-drive migration |

## Fixes added during review

- `f55f936`: layered settings reads reject missing/unmounted volumes, including
  stale settings files on an unmounted directory. Two real-file regressions
  failed before the fix; 217 final focused tests pass.
- `ea3a658`: the persistence migration checks every real `mv` result before
  binding. An interrupted migration retains an identity-bound pending record;
  retries refuse destination collisions rather than overwriting state. Three
  real-file/production-command tests cover failure, completion and collision.
  The QEMU run also reproduced a real read-only-source move failure and proved
  that it remains pending, then verified the repaired migration and bind.

## Actual QEMU scope

QEMU TCG, Linux/Proxmox installer live environment, fresh disposable 64 GiB
virtual disk serial `CODEXTEST40101`, isolated virtual NIC without host network
connection. Neither physical drive was attached. Python 3.13 runs the carried
production libraries and production HTTP server. No fake runners, mocked
commands, replacement services or simulated cryptography are used in this
integration check. Application sessions and encryption values are generated
only for this disposable lab; PAM and Proxmox GUI login are not tested.

Five checks cover actual tmpfs mounts, shared settings across two OS identifiers,
unmounted-read refusal, actual failed `mv`, collision refusal/retry, real bind
mounts, and OpenSSL encryption/decryption with wrong-passphrase refusal. Nine
production GET routes return 200: `/home`, `/tools`, `/environments`, `/network`,
`/sensors`, `/launcher`, `/vault`, `/ai-setup`, `/power`. This proves HTTP handling;
it does not prove browser rendering, functioning guest VMs, host diagnostics,
provider authentication or power actions.

The first runtime attempt passed the five filesystem/crypto checks but failed
HTTP because the live installer's loopback was down. After `ip link set lo up`
the check passed. The original serial trace retains both attempts. A separate
historical `rehearsal-old-pve.raw` COW boot reached root-filesystem discovery but
did not establish application readiness; it was stopped and its overlay check
passed. The active shared rehearsal disk was locked and was left alone.

The full host unit run recorded 3,861 passed, 263 failed, 114 errors, 3 xfailed
and 9 passing subtests. Of the failures/errors, 375 were `Operation not permitted`
and two were console timeouts. No assertions were weakened or tests skipped to
claim a green suite. The final relevant subset passed **217 tests**. See the
preserved logs; host socket limitations are distinct from the successful guest
HTTP checks.

## Test artifact and repeatable acceptance

Artifact directory:
`/run/media/cane/CACHE/baseline-build/codex-pc401-runtime-20261015`.
Use `pc401-disposable-test-final.iso` and its SHA256/source verification JSON.
This is a bootable source/cache carrier based on the publisher ISO, with no
embedded answer/password and no unattended first-boot hook. It is not a claim
of a newly installed Baseline system. All staged files are independently
extracted and hash-compared; the source cache's 491 files were verified before
building. No shared input was modified.

Create a fresh disposable disk and boot the ISO with the same isolated setup:

```sh
qemu-img create -f qcow2 /tmp/pc401-test.qcow2 64G
qemu-system-x86_64 -machine pc,accel=tcg -cpu max -m 4096 -smp 2 \
  -netdev hubport,id=net0,hubid=0 -device e1000e,netdev=net0 \
  -drive if=none,id=baseline,file=/tmp/pc401-test.qcow2,format=qcow2 \
  -device virtio-blk-pci,drive=baseline,serial=CODEXTEST40101 \
  -boot d -cdrom /absolute/path/pc401-disposable-test-final.iso
```

Select the graphical installer, then open its disposable root shell on tty3
with Ctrl+Alt+F3. No installation or disk formatting is needed for these checks:

```sh
ip link set lo up
BASELINE_DISPOSABLE_QEMU_ACCEPTANCE=1 python3 \
  /cdrom/baseline-src/tests/integration/verify_pc401_disposable_guest.py \
  --source-root /cdrom/baseline-src
```

The script refuses to run without the exact disposable-disk identity and explicit
lab flag. It removes its real mounts before reporting success. Never substitute
a physical PC401/PC601 path into this command.

## Remaining acceptance and repair tasks

1. **PC401-308-01 — Proxmox routing:** production `bind_fstab_line` still routes
   `/var/lib/pve-cluster` through USER_PERSONAL when persona is personal, despite
   DR259 requiring USER_ADMIN. See the direct production-function result in
   `proxmox-persona-routing-review.json`. Pin host state independently of active
   persona and verify switching without unmounting a live Proxmox database.
2. **PC401-308-02 — Installed Proxmox migration:** boot/reboot a disposable
   installed guest with the new drop-ins; prove pmxcfs database retention,
   service startup and fail-closed behavior when USER_ADMIN is unavailable.
   Existing migration directories created by older failed code need inspection;
   they predate pending records and are not automatically repaired by this fix.
3. **PC401-308-03 — Installation harness:** the imported allscript rehearsal
   still uses `fetch_from="iso"`; AGENTS requires the HTTP answer-server path.
   It was not invoked here. Reconcile that path before an unattended rehearsal.
4. **PC401-308-04 — Physical acceptance:** this namespace still lacks block-device
   nodes and `/dev/kvm`. Re-resolve PC401 by serial, inspect use-state and recovery,
   then perform the guarded update and native GUI/login/NIC/firewall/persistence
   checks. No physical deployment was performed in this session.
5. **PC401-308-05 — Workloads:** implement guest settings application, default
   installed/configured apps and broader OS acceptance under DR258/259.

The candidate is ready for the isolated tests above. Installed-drive deployment
is blocked by the explicit routing/migration tasks. Queue72/74/75/76/78 stay open.

Committed serial/full-suite logs are display-normalized (terminal controls and trailing whitespace removed). Raw bytes and their SHA256 hashes are retained at the paths in `log-provenance.json`.
