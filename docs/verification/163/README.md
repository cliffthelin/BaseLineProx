# DR163 evidence — 2026-10-05

- focused-tests.txt: 164 unit tests passed. VM runners are fakes; direct handlers
  and job SQLite checks do not establish actual guest/browser execution.
- native-overlay-checks.json: actual qemu-img/qemu-io/xorriso operations on
  synthetic blank images, production Ubuntu seed/create/rebuild code. ISO
  extraction verified the selected configuration, disk readback verified reset,
  SHA256 verified unchanged backing and retained disks. This is native artifact
  proof, not Ubuntu source provenance, user-file filesystem retention or boot.
- native-base-checks.json: actual conversion/receipt/tamper-refusal proof on
  synthetic images. No publisher image downloaded or guest booted.
- runtime-blockers.json: actual web/browser runtime attempts were blocked by
  socket denial and Chromium IPC failure. KVM/graphics devices and native
  Proxmox commands are not exposed in this session. No runtime success inferred.

Temporary native test seeds/account hashes were removed with the disposable
fixture; no passwords, hashes, seed contents or operator credentials published.
No physical target drives accessed or changed. Earlier DR117 GUI evidence is
historical and does not validate the code or kiosk gates changed in DR163.
