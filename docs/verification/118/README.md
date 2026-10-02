# DR118 evidence — 2026-10-01

`distro-live.json` was retrieved directly from the approved disposable Proxmox clone after the native production create/boot/shutdown/rebuild tests. Eleven successes and one openEuler setup failure are retained verbatim. VMIDs/config/origins are actual, not unit-fixture output. No password or shadow hash is included.

`container-page.html` and `vm-page.html` are authenticated HTTP responses from the final deployed clone source. They contain the actual host catalog, retained-container state and the honest status of nine requested systems. They do not establish those requested systems boot successfully.

An additional real web test created Alpine CT125, checked a fresh one-time login, cleanly stopped and rebuilt it, and checked that `/home/web-proof` survived while `/etc/web-os-proof` disappeared. Anonymous GET redirected to login; wrong synthetic root password returned HTTP401. All changes stayed in the disposable clone; no physical drive writes.

The full hardware-guarded unit-suite result and final source fingerprints are appended below after completion. Unit runners are fakes; live checks above used actual Proxmox in KVM, not bare metal.

Final checks: **2,862 unit tests passed in 121.36 seconds**, with the hardware
guard active and temporary files under the repository's `.test-work-118/`.
`tools/check_provision_deploys_all_imports.py` and `git diff --check` passed.
`source-sha256.json` fingerprints the final implementation and tests.
Final authenticated page checks passed for all nine requested names, UEFI and
retained-size controls, and the disabled openEuler selector.
These page controls have fake-backed unit coverage; the requested ISO boots
and distro-specific retained mounts have not been verified.
