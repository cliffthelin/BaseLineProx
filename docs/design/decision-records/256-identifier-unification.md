# DR256 - One identifier model: global reference, local constant, external identity

Date: 2026-10-11. Status: approved by the operator 2026-10-11 (all three decisions) and implemented: `identifiers.py`, `references.py`, `machine_context.py`.
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

## Decisions (operator, 2026-10-11: approved all three) and what was built

1. **Portable identities (special `02`).** `identifiers.mint_portable` is deterministic from its first parent; `reparent` moves it when the
   data moves to other hardware; the identifier never changes and only portable ones may move.
2. **Role volumes.** `references.link_roles`: BASELINE, INSTALLER_CACHE, `USER_*`, `APPDATA_*` are portable; SUBSTRATE and SESSION_TEMP are
   fixed to the host. First boot links them in a new `machine` step after storage.
3. **Rollout.** Done: naming, gateway routes, drive enrollment, repair events, handoff, GPUs, interface aliases, container VMIDs, storage
   roles, `references.backfill()`. Remaining: settings_store, installer_cache, harness_events, vm_host.

## A mismatch is a state with behaviours, never a failure (operator direction)

A chain of identifiers that does not match, or has not been set up yet, must not break or deny anything. It selects behaviour.
`machine_context.py` keeps a profile per machine the drive has run on (registry `machine_profiles`, GLOBAL) and compares the current
machine's fingerprint (DMI system UUID, board and chassis serial are identity; CPU, memory and so on are parts):

| State | Meaning | Behaviour |
|---|---|---|
| `first_machine` | no profile yet | record it as the installer host |
| `known` | fingerprint matches | note the visit |
| `changed` | same machine, parts differ | queue a recheck of what depends on those parts |
| `new_machine` | no profile matches: the drive moved | record a new profile; queue discover-hardware, check installer cache, check app data, check user data (deterministic, due once the substrate is up) and rebuild-vm-config, resolve-incompatibilities (need a helper) |
| `unreadable` | fingerprint not available | treated as unknown; retry later |

Queued work (`adaptation_tasks`) is released by readiness: deterministic tasks as soon as their own stage is up; anything that cannot be
settled deterministically waits until substrate, GUI, browser, internet and AI are all up, because that is when something exists to help.
`defer(task, reason)` marks a task the deterministic code could not settle so it goes to the helper. The old profile is never used as if
it were the new machine, access is never denied, and the drive builds up as it discovers.

Built: the state model, queue, release rules and the first-boot record. Not built: the executors for each task kind and the boot-time
service that runs `observe` on every boot; those come next and each task kind fills in against the same queue.

## Not changed

Naming codes and their uid/alias derivation, registry keys, LVM naming, fstab/PARTUUID handling, guard behaviour, Codex's USER_ADMIN record.
