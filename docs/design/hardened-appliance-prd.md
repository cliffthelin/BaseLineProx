# PRD: Hardened workstation appliance - dual-GPU host, Caddy gateway, measured boot

Status: draft. Design plus a first pure-code slice (§13). Nothing in §13's first slice touches a real drive or the real TPM. Drive steps are in §11 and §15.
Source: an architecture blueprint pasted by the operator on 2026-09-30 (written by another AI assistant, not by this project). It is treated as *requirements input*, reconciled against the code that actually exists (§3), not copied as truth.
Depends on: `registry.py`, `settings_store.py`, `gpu_admin.py`, `quadlet.py`, `dependencies.py`, `testpersistence-prd.md` (identity/ledger integrity).
Blocked by: nothing for §13's slice. Anything touching real IOMMU/VFIO, LUKS or TPM sealing is hardware-gated (§11).

## 1. Problem and goal

Turn one high-end consumer machine (Ryzen 9 7900X, B650E board, AMD iGPU, RTX 3070 + Tesla P40, 96 GB RAM) into a deterministic appliance: Proxmox host drives the local display from the iGPU so both NVIDIA cards keep clean VRAM; a single reverse proxy fronts all services; configuration is hashed and bound to the TPM so tampering locks the data instead of silently running.

## 2. Non-goals and omissions

- The blueprint's closing "Medical Disclaimer" and its trailing offer to write code are chat boilerplate, not requirements. Omitted.
- No ZFS/TrueNAS 100 TB array work until the operator confirms that storage exists (§12, Q4).
- No BIOS automation. UMA frame buffer, SVM, IOMMU, ACS override are operator steps; this project can only *check and report* them.
- No wholesale reinstall as the answer to configuration change (standing correction, see memory `qcow2_overlay_vs_disposable_substrate`).

## 3. Reconciliation with the current project

Already built (do not redo): host display gate `kiosk_gate.py` / `browser_policy.py`; bridge config `ifnet_config.py`; hardware collector `hardware.py`; GPU detection + six per-device modes `gpu_admin.py` (record 94); container GPU wiring `quadlet.py` (record 96); registrar `registry.py` with GLOBAL vs PROTECTED scope; encrypted-persistence identity/ledger design `testpersistence-prd.md`. Not built: Caddy, TPM/PCR measurement, LUKS enrollment, IOMMU/VFIO host prep, desktop VM.

Conflicts found in the blueprint (each needs a decision, none is silently resolved):

| # | Blueprint says | Problem | Proposed handling |
|---|---|---|---|
| C1 | RTX 3070 -> desktop VM, P40 -> AI VM, fixed | Contradicts the standing rule "detection narrows what exists, never which mode" and the operator's stated primary use (all VRAM to one compute workload, occasional video) | Treat as one selectable *profile* on top of `gpu_admin` (`vfio_passthrough` per device), never hard-wired |
| C2 | Test 1.1: both cards bound to `vfio-pci`; Test 1.2: host `nvidia-smi` reads 0 MB / 8192 MB | Mutually impossible: with no host `nvidia` driver bound, host `nvidia-smi` cannot see the cards at all | Replace 1.2 with "host has no NVIDIA driver loaded and no process holds `/dev/nvidia*`" |
| C3 | Extend manifest hashes into PCR 12 and 13 | systemd-stub already measures kernel cmdline/credentials (PCR 12) and sysext (PCR 13); reuse collides with them | Choose PCRs deliberately after research R-2; do not hardcode 12/13 (verify against current systemd TPM2 PCR registry) |
| C4 | Hash `device_layer.json` / `application_layer.json` | The project's config now lives in SQLite registries (`registry.py`); a raw `.db` hash is unstable (WAL, page reuse) | Layer manifest = canonical JSON export of selected GLOBAL-scope registry entries, hashed; never the raw DB file |
| C5 | Seal disk keys to PCRs covering config | Legit settings changes (which happen constantly here) would lock the disk: the "brittle boot deadlock" the blueprint's own R-3 warns about | Seal to a small stable set (firmware, secure boot, kernel); config integrity is checked by signed-manifest verification (R-3), not by PCR sealing alone |
| C6 | "Run community Post-Install script"; ProxMenux | Remote script execution; project rule (provision.sh) is pinned + sha256-verified fetch only | Vendor or pin+verify; no `curl \| bash` |
| C7 | AI VM gets 32 GB RAM yet runs 120B+ models fed by "90 GB system memory" | Internally inconsistent | Size from a real model (e.g. a 118 GB MoE with `--n-cpu-moe` + NVMe handoff), decided at VM-creation time by the operator |
| C8 | "7-container topology" | Never enumerated | Open question Q2 |

## 4. Requirements

IDs follow the blueprint's component numbers. Status: `todo`, `partial`, `hw` (needs real hardware and operator).

**Component 1 - host and interface**
- R1.1 Proxmox on a dedicated NVMe boot drive; bridge `vmbr0` shielded from desktop tools. `partial` (`ifnet_config.py`); install itself `hw`.
- R1.2 iGPU-only host display; minimal Xorg+Openbox or Cage; Chromium kiosk pinned to loopback admin endpoints. `partial` (`kiosk_gate.py`, `browser_policy.py`); BIOS UMA `hw`, report-only check `todo`.
- R1.3 Research: can the browser runtime be a distroless/immutable container image instead of Debian userland. `todo` (R-1).

**Component 2 - hardware isolation and GPU mapping**
- R2.1 IOMMU: `amd_iommu=on iommu=pt`; blacklist `nouveau`/`nvidia` on the host when VFIO mode is chosen; verify IOMMU groups. `todo`, read-only verification first, changes `hw`.
- R2.2 Verify isolation of the 3070 and P40 via `gpu_admin` evidence; apply VFIO binding only when the operator selects `vfio_passthrough` for that device. `partial`.

**Component 3 - Caddy overlay**
- R3.1 Single gateway with local TLS and header stripping, declarative Caddyfile. `todo` (first pure generator in §13 follow-up).
- R3.2 Path routing (`/chat`, `/media`, `/data`) sourced from a registry type, not hand-edited. `todo`.
- R3.3 Research: Authentik/Authelia forward-auth for RBAC. `todo` (R-4).

**Component 4 - measured boot and locking**
- R4.1 `systemd-cryptenroll` binding of LUKS keys to TPM2; ties to `testpersistence-prd.md` key/ledger design. `hw`.
- R4.2 Per-layer manifest hashing at provision time and PCR extension. `todo`, first slice in §13.
- R4.3 Research: detached signed-manifest pipeline so config changes never require TPM clearing. `todo` (R-3).

## 5. Topology (corrected diagram)

```
  physical monitors
        |
  [ AMD iGPU + UMA carve-out ]  <- host display only
        |
  [ Proxmox VE host ]  boot: dedicated NVMe   trust: fTPM (AMD PSP) / TPM 2.0
        |                                  |
   VFIO or container-CDI                   |
   (operator-chosen per GPU)               |
        |-- Tesla P40 -> AI compute workload (VM or container)
        |-- RTX 3070  -> media/desktop workload (VM or container)
        |
  [ Caddy gateway ]  https://baseline.local  -> /chat /media /data, RBAC in front
        |
  [ storage backplane ]  future, hardware-gated (Q4)
```

## 6. Dataflow

1. Firmware/secure boot measurements land in the firmware PCRs.
2. Provisioning exports each layer's registry entries to canonical JSON, hashes them (R4.2), records the manifest digest, and extends the chosen PCR.
3. TPM releases the sealed key only if the sealed PCR set is unchanged; config integrity is separately proven by the signed manifest (R-3).
4. Host brings up the iGPU display; Caddy routes to backends.
5. Inference: requests go via Caddy to the compute workload; GPU/RAM/NVMe tiering per operator's chosen mode.

## 7. Gap analysis

| Vector | Today | Target | Why |
|---|---|---|---|
| GPU VRAM contamination | Desktop shell on a discrete card costs 1.5-3 GB | iGPU owns display; discrete VRAM clean | Max model headroom |
| State separation | Registry scopes exist; app data placement not enforced (queue 22) | Code, settings, persistent data separated and enforced | Contain compromise |
| Boot security | Config unverified at boot | Manifest hashed + signed; disk keys TPM-sealed | Tamper -> lockout, not silent run |
| Interoperability | Volume-to-volume only | Caddy path routing + `.network` units (queue 20) | Decoupled sandboxed services |

## 8. Roadmap (gated, no calendar promises)

- H0 (this PRD, no hardware): PRD, canonical manifest + PCR-extend plan (pure, injected runner).
- H1 (read-only on real host): report IOMMU groups, iGPU/UMA status, kernel cmdline state via `gpu_admin`/`hardware`.
- H2: Caddyfile generator from a registry type; render-only, validated with `caddy validate` if installed.
- H3 (operator present): VFIO profile applied to one device in QEMU first, then real hardware.
- H4: forward-auth (R-4) spike.
- H5 (operator present): `systemd-cryptenroll` on a *scratch* volume, never a real data volume.
- H6: signed-manifest verification at boot (R-3).

## 9. Acceptance cases (blueprint's suites, corrected)

- A1.1 Both GPUs bound to `vfio-pci` when VFIO profile selected (`lspci -nnk`). `hw`
- A1.2 (replaces blueprint 1.2) Host has no NVIDIA driver loaded and no holder of `/dev/nvidia*`. `hw`
- A2.1 Authenticated request via gateway returns 200 from the routed backend.
- A2.2 Direct request to a backend port from another LAN host is dropped (timeout).
- A3.1 Unmodified layer manifest produces the same digest across runs and across process restarts (pure, testable now).
- A3.2 Any single-byte change to layer content changes the digest (pure, testable now).
- A3.3 Whitespace/key-order changes in the *source registry export* do not change the digest (canonicalization, testable now).
- A3.4 Sealed-key release is withheld after a measured-state change. `hw`, scratch volume only.

## 10. Research items

R-1 distroless browser runtime; R-2 PCR allocation vs systemd-stub/UKI; R-3 detached-signature config verification (asymmetric key, offline signing, no TPM clear on legit change); R-4 Authentik vs Authelia behind Caddy `forward_auth`. Each closes with a short note, not code: all four are in §14.

## 11. Safety constraints

Drives are identified by serial, never by kernel letter (letters shift between boots; see the audit, A1). Only the pinned scratch drive (serial `MD89N41071210AP4E`) may be written, and every other drive is off-limits, including the Proxmox substrate (serial `FD01N6557110C271B`). No LUKS, TPM clear/seal, or driver blacklist on the real host without the operator present and a QEMU proof first. Privileged steps are given to the operator to run; this project does not attempt sudo workarounds. All fetches pinned + sha256.

## 12. Open questions for the operator

- Q1 Is the target really to move both NVIDIA cards into Proxmox? Earlier stated plan was Ubuntu keeps the NVIDIA cards and Proxmox uses the iGPU.
- Q2 What are the "7 layers/containers"?
- Q3 Desktop VM OS (Omarchy / FydeOS / NixOS) or just the host kiosk?
- Q4 Does the 100 TB array exist, and behind which controller?
- Q5 Is the TPM here a discrete module or AMD fTPM? (`/dev/tpm0` and `/dev/tpmrm0` present on the dev machine; `tpm2-tools` not installed.)

## 13. First slice (started)

`baseline/lib/measured_boot.py`: pure canonical-JSON layer manifests, SHA-256 digests, TPM PCR-extend arithmetic (`new = H(old || digest)`) for verification, and a runner-injected `extend_pcr` that shells to `tpm2_pcrextend` only when a caller supplies a real runner. Tests cover A3.1-A3.3. Not wired into `provision.sh` yet.

### 13.1 Second slice (done): gateway renderer (R3.1 / R3.2)

`baseline/lib/gateway_config.py`: `render_caddyfile(site, routes, forward_auth=None)`. Pure text output, deterministic (routes sorted), `tls internal`, strips `Server` / `X-Powered-By`, unmatched paths return 404, optional `forward_auth` (R-4 spike hook). Site, path, upstream and forward_auth values are validated against strict patterns so a newline or brace cannot inject Caddyfile directives; duplicate paths are rejected. Tests: `tests/unit/test_gateway_config.py`. Not yet done: sourcing routes from a registry type, and `caddy validate` (caddy is not installed on the dev machine). The blueprint's A2.1 "200 OK" needs a live backend and stays hardware/integration-gated.

### 13.2 Third and fourth slices (done)

- **H1 host readiness** (`baseline/lib/host_readiness.py`, 10 tests): `collect(fs)` reads sysfs/procfs through an injected reader, `evaluate(snapshot)` is pure. Run against the dev machine on 2026-09-30 it reported: IOMMU active (29 groups, each NVIDIA card isolated), kernel cmdline missing `amd_iommu=on iommu=pt` (warn), **no AMD iGPU on the PCI bus (fail: disabled in BIOS)**, both NVIDIA cards on the host driver (info only; mode is operator-chosen), TPM 2.0 present, Secure Boot off or unknown, `tpm2_pcrextend` not installed. Secure Boot detection is not implemented in `collect` (reports unknown).
- **R3.2 gateway routes in the registry** (`baseline/lib/gateway_routes.py`, 6 tests): routes are GLOBAL-scope `gateway_route` entries, validated at write time with `gateway_config`'s checks; `manifest_entries()` feeds `measured_boot.layer_digest("gateway_layer", ...)`. Added `registry.delete_entry`.
- **R-2 data point:** on the dev machine's current Ubuntu boot PCRs 11, 12, 13 and 15 read zero and PCR 14 is nonzero, so 12/13 are unused *on this boot*. A Proxmox/UKI boot may differ; R-2 stays open.

## 14. Research notes (2026-09-30)

Sources were fetched this session; points marked *(unverified)* come from memory or a search summary, not a primary document.

**R-2 PCR allocation - closed, and it changes the design.** The UAPI Linux TPM PCR registry ([spec](https://uapi-group.org/specifications/specs/linux_tpm_pcr_registry/)) assigns PCR 11 to systemd-stub (UKI components), **PCR 12 to kernel command line, credentials and config images, PCR 13 to initrd system extensions**, PCR 14 to shim (MOK), and PCR 15 to systemd services (root-FS key, machine-id). So the blueprint's 12/13 are owned by systemd-stub; reusing them collides with a UKI boot (C3 confirmed). They happen to read zero on this machine's current non-UKI Ubuntu boot, which is luck, not a guarantee. PCRs 16-23 are documented there only as application/local use. Measured-boot's manifest digest should go to a local-use PCR *(which one, and whether it is resettable by userspace, is unverified: confirm against the TCG PC Client profile and the target TPM before choosing)*, never 12/13.

**R-3 signed-manifest path - closed, and it resolves C5.** `systemd-cryptenroll` already supports the pattern the blueprint wanted ([man page](https://man7.org/linux/man-pages/man1/systemd-cryptenroll.1.html)): `--tpm2-public-key` / `--tpm2-public-key-pcrs` bind the secret to the public half of a signing key instead of to fixed PCR values, so a signed policy for each new kernel/initrd lets the volume unlock across updates without re-enrolling (default signed PCR is 11). The same page recommends direct binding to a combination of PCRs 7, 11 and 14, and notes PCRs 0 and 2 are already covered indirectly through PCR 7. Design consequence: seal the disk to PCR 7 (+ signed PCR 11 policy); treat *config* integrity as a separate signed-manifest check (sign `layer_digest` output offline), so legitimate settings changes never lock the disk and never need a TPM clear. `--tpm2-pcrlock` (systemd-pcrlock) is the alternative policy mechanism, to be evaluated in H5 on the scratch volume.

**R-4 gateway auth - closed for the integration shape, open for the product choice.** Both Authelia and Authentik work behind Caddy's `forward_auth` ([Caddy docs](https://caddyserver.com/docs/caddyfile/directives/forward_auth), [Authelia + Caddy](https://www.authelia.com/integration/proxies/caddy/)). Authelia is forward-auth middleware with per-path/group/network access rules and is small; Authentik is a full identity provider (OIDC, SAML, LDAP, RADIUS) with its own admin UI. For a single-operator appliance Authelia fits; pick Authentik only if LDAP/SAML provisioning is needed *(comparison from search summaries)*. Bug found and fixed while researching: `gateway_config` emitted the obsolete `/api/verify` endpoint; it now emits `/api/authz/forward-auth` with `copy_headers Remote-User Remote-Groups Remote-Email Remote-Name` (needs Caddy >= 2.5.1).

**R-1 distroless browser - open, leaning no.** Project Hummingbird ([Red Hat article](https://developers.redhat.com/articles/2026/04/28/exploring-distroless-containers-project-hummingbird)) ships distroless images with no package manager and mostly no shell; the published list covers language runtimes, databases, web servers (including Caddy) and tools, and I did not see a browser image *(from a search summary, not the image catalogue)*. A kiosk Chromium needs GPU/display libraries, fonts and a compositor, so a distroless browser image is unproven. Reasonable near-term target: run **Caddy** from a Hummingbird image (it is listed) and keep the kiosk browser on the host; revisit the browser once the catalogue is checked directly.

## 15. Scratch drive record (2026-09-30)

At the operator's instruction, serial `MD89N41071210AP4E` (`/dev/sdd` at the time; the docs' former "persistence backend", recorded disposable in DR46) was repartitioned with `boot/prepare_scratch_drive.sh`: GPT with `proxmox-rehearsal` 200G (raw), `luks-scratch` 100G (empty, for H5), `scratch-data` 176.9G (ext4). It previously held an `iso9660` Omarchy image. The kernel has not re-read the table (needs root: `sudo partprobe`). See `docs-vs-code-audit-2026-09-30.md` A1-A2 for the documentation fallout.

**Correction (same day):** the layout above is *not* Baseline's. It was improvised and bypassed `physical_device_safety` / `drive_installer` (decision record 49: no ad hoc destructive commands). Baseline defines, in `drive_installer.py`, these volumes on one drive as LVM logical volumes in a volume group: `BASELINE` (5-50G), `INSTALLER_CACHE` (50-200G, noexec), `SESSION_TEMP` (5-50G, noexec), `SUBSTRATE_PERSISTENCE` (1G, noexec), and one `USER_PERSISTENCE_<PERSONA>` (50-200G) per persona (default `admin`, `personal`). `compute_adaptive_plan` on this 512 GB drive gives 31 / 136 / 31 / 1 / 136 / 136 GB. `boot/prepare_scratch_drive.sh` is now disabled. The `agentIndex.md` files written to the drive and in `boot/agentindex/` describe the improvised layout and must be regenerated per Baseline's volumes.

**Resolved (same day):** serial `MD89N41071210AP4E` was re-laid out through `baseline/lib/carrier_layout.py` (11 tests; validates with `physical_device_safety`, sizes with `drive_installer.compute_adaptive_plan`, tests first). Six GPT partitions named for Baseline's volumes, ext4 inside, formatted by byte offset, no LVM and no root: `BASELINE` 31G, `INSTALLER_CACHE` 136G, `SESSION_TEMP` 31G, `SUBSTRATE_PERSISTENCE` 1G, `USER_PERSISTENCE_ADMIN` 136G, `USER_PERSISTENCE_PERSONAL` 136G. Each has a generated `agentIndex.md` in its root. Verified with `sgdisk -p`, `e2fsck -fn` (clean on all six) and reading each index back. The kernel has not re-read the table (`sudo partprobe`), so `/dev/sdX1-6` do not exist yet; the volumes are not mounted, so `noexec` etc. apply at mount time. The earlier 200G/100G/176.9G layout is gone. The `proxmox-rehearsal` and `luks-scratch` partitions no longer exist, so H3/H5 need their own scratch target.

**Placement (2026-09-30):** this PRD's code, tests and docs (14 files, `MANIFEST.sha256` included) are on the `BASELINE` volume at `/hardened-appliance/`, and a tarball of that content, built with `backup_restore.create_backup`, is at `INSTALLER_CACHE:/seed/baseline-seed.tar.gz` (decision record 76's convention). Written by byte offset (no mount); verified by re-reading every file against the manifest, comparing the tarball byte-for-byte, and a clean `e2fsck` on both volumes. The repo remains the source of truth; the drive holds a copy as of this date.
