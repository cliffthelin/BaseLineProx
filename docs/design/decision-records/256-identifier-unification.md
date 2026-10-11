# DR256 - One identifier model: global reference, local constant, external identity

Date: 2026-10-11. Status: proposed for operator approval; the library parts are implemented (`identifiers.py`, `references.py`).
Builds on DR89 (foundation registry), `naming.py` (2026-09-30 direction), DR254/DR255. Requirement from the operator: unify the
patterns so they are cohesive and optimal, and lose none of the identifiers already discussed.

## The three kinds of identifier that already exist

1. **Local constants** (`naming.py`, `A_C_00001`). Nine characters, allocated once, never reused, never carrying a human name. They exist
   because ext4 labels are 16 characters, udev/systemd/fstab/overlay/podman syntax constrain what a name may contain, and owner uids
   are derived from them (`baseline-a_c_00001`). Aliases (`by-name/caddy`) point at them and are never a mount path.
2. **External identities** observed on the machine, which Baseline did not name and which can change: drive serial, GPT disk GUID,
   PARTUUID, filesystem UUID and label, LVM PV/VG UUID, LUKS UUID, MAC/interface name, GPU CDI UUID, Proxmox VMID, machine-id.
   The persistence design (testpersistence PRD) also requires a logical store identity to survive migration to replacement hardware.
3. **Registry keys of each registry type** (DR89): drive serials in `drive_enrollment`, disk GUIDs in `installer_drives`, route ids,
   setting keys, dependency ids, interface aliases, GPU devices.

Before DR255 there was no identifier that was the same across all of them; each registry pointed at the others by whatever string it had.

## The model

| Tier | What | Stable? | Used for | Lives in |
|---|---|---|---|---|
| **Global reference** | DR255 identifier (128-bit, hierarchical) | forever; never re-minted | the only value one component hands another: events, registry cross-references, packets | `baseline_identities` |
| **Local constant** | `naming.py` code | forever | mounts, labels, units, uids, by-name aliases: places with a syntax or length limit | `baseline_ids` |
| **External identity** | serial, PARTUUID, fs UUID, VG UUID, LUKS, MAC, CDI, VMID... | no: a reformat or replacement changes it | evidence and lookup only; never an identity | `baseline_external_map` (`scheme:value` -> identifier) |

Rules:

1. **Every thing has exactly one global reference.** A naming code and an external identity are *attributes of* that reference, not
   rivals to it. `references.link_naming(code)` ties a code to its reference; `identifiers.map_external(...)` ties an external identity.
   Nothing is renumbered or renamed: codes, labels and registry keys stay exactly as they are.
2. **Components exchange global references, not local constants or external identities.** A message says `source_ref` / `subject_ref`.
   Local constants appear only where a syntax limit forces them (a mount option, an fstab line, a unit name).
3. **An external identity never *is* the identifier.** It is recorded against one, so when a disk is reformatted (new PARTUUID) or
   replaced (new serial) the reference stays and the cross-map gains or updates a row. History is the cross-map plus `registry_events`.
4. **Deterministic by default, mapped by exception.** Things Baseline names itself (host, substrate, VM, application, role volume) are
   minted from parent + kind + name, special byte `00`: same inputs, same identifier, on any rebuild. Things it observes and cannot name
   (a foreign disk, a MAC, a GPU) get a random own id with special byte `01` recorded once in the cross-map.
5. **Scheme-keyed cross-map.** The key is `scheme:value` (`partuuid:...`, `fsuuid:...`, `mac:aa:bb:...`, `vmid:120`, `serial:...`), so the same
   UUID appearing as a PARTUUID and a filesystem UUID cannot collide.
6. **Registry keys do not change.** Each registry keeps its own key (drive serial, GUID, route id); `references.link(type, key, kind=...)`
   adds the global reference beside it. Migration is additive and tolerant (nothing breaks on a machine with no host id).

## Where each previously discussed identifier lands

| Identifier (source) | Tier / handling | Reference kind |
|---|---|---|
| Installer lane UUID (`baseline/INSTALLER_UUID`, DR254) | lane digits 0-7 of every host id | - |
| Drive serial (enrollment, guard, LVM binding) | external `serial`; also digits 8-15 as a hint; the host id binds the full serial through its hash | host / hardware |
| GPT disk GUID (`installer_drives`) | **is** the host identifier, set on the disk | host |
| PARTUUID / fs UUID / label (appdata, fstab roles, DR137, DR157) | external, `partuuid` / `fsuuid` | hardware under the host |
| LVM PV/VG UUID, `baseline_<hash of serial>` names (DR144/146) | external `pvuuid` / `vguuid`; the LVM name rule is unchanged | hardware / substrate |
| LUKS UUID, GPT/LUKS evidence (testpersistence PRD) | external `luks` | hardware |
| Naming codes `U_/A_/S_/O_` + medium (`naming.py`) | local constant, linked at allocation | application / vm / substrate by cluster+medium |
| Owner uids `baseline-<code>`, `by-name/` aliases | derived from the code, unchanged | - |
| Proxmox VMID, base VMID (distro_containers, container_backup) | external `vmid`, mapped when a VM/container is created | vm |
| GPU CDI UUID (`gpu_admin`) | external `cdi` | hardware |
| MAC / interface name, operator display names (`network` aliases) | external `mac`; display name stays an alias | hardware |
| Gateway route id, setting key, dependency id | registry key unchanged; reference where another component needs to cite it | substrate |
| Persona / persistence store | logical store: minted as a deterministic substrate identifier; see decision 1 | substrate |
| machine-id (inventory redaction keys) | external `machine-id`; redaction hashes unchanged | host |

## Special byte (digits 30-31)

`00` ordinary; `01` external mapping (non-deterministic); `02` is proposed below; `03-7f` reserved; `80-ff` experiments. Unknown values are
treated as special, never ordinary.

## Decisions for the operator

1. **Portable identities.** A persistence store must outlive the drive it sits on, but digits 8-15 of its identifier name a drive. Proposal:
   special `02` = portable: digits 8-15 are the *origin* hint only; the registry `parent` is the authority and may change on migration;
   the identifier itself never changes. Without this, a migrated store would need a new identifier, which breaks the "never re-minted" rule.
2. **Reference kind for role volumes.** Deterministic substrate identifiers per role (`USER_PERSISTENCE`, `INSTALLER_CACHE`, ...) so
   every storage record can cite them. Adds eight to ten entries per host; no change to labels or fstab.
3. **Order of the remaining rollout.** gpu_admin, network aliases, vm_host/distro_containers, storage volumes, settings_store, installer_cache,
   harness_events, then a one-shot `references.backfill()` for entries created before a host id existed.

## Not changed

Naming codes and their uid/alias derivation, registry keys, LVM naming, fstab/PARTUUID handling, guard behaviour, Codex's USER_ADMIN record.
