# Decision record: GPU Administration - real detection, never auto-decided mode

Status: **implemented, unit-tested (1452/1452 full suite, up from 1422), and verified for real against this session's own actual hardware (RTX 3070 + Tesla P40).**

## What was asked

A multi-turn design conversation (not a single instruction) converging on: detect the real GPUs on a machine, determine which of several real hardware-sharing modes each one can actually support, and let the operator choose - explicitly **not** auto-choosing for them. Direct instructions along the way:

- "It cant all be auto detect as we mentioned like half a dozen choices. Those choices dont necessarily go away unless we force modes a user doesnt want" - auto-detection may narrow *which GPUs exist*, never *which mode each one runs in*.
- "When i run this on my laptop with all different hardware this is where we cant lock it down unless its chosen by the user" - the option set itself must be computed per real machine, not assumed from this one.
- "Yes, that's it — build it that way" - confirming the design before implementation.

## The six real modes (researched directly, not assumed)

`host_display`, `vfio_passthrough`, `vgpu_mdev_split`, `sriov`, `virtio_gpu_shared`, `container_passthrough` - each with a real, verifiable, live signal wherever one exists, never a hardcoded per-vendor guess where a kernel-exposed fact is checkable instead:

- **`mdev_supported_types`** (sysfs) - existing and listing types means vGPU/mdev works *right now*, under whatever driver is currently loaded.
- **`sriov_totalvfs`** (sysfs) - nonzero means real SR-IOV capability, with a real virtual-function count.
- **A DRM render node** mapped from `/sys/class/drm/renderD*/device` back to the PCI address - needed for both `virtio_gpu_shared` and `container_passthrough`.
- **`nvidia-ctk`/`nvidia-container-cli` on PATH** - checked for real (not assumed installed just because `nvidia-smi` is present, which this session's own machine disproved: `nvidia-smi` exists, the container toolkit doesn't).
- **`pci_class`** - `host_display` is only offered when the device is a real "VGA compatible controller"; a "3D controller" (like a Tesla P40 - no video output at all) never gets offered that choice, because offering it would just fail.

**Two different, both honestly labeled, kinds of evidence for `vgpu_mdev_split`**: a live sysfs check (`mdev_supported_types` present = working now) is different from a static, sourced table of known-vGPU-capable PCI IDs (`KNOWN_VGPU_CAPABLE_IDS`, seeded with the Tesla P40's real ID from this session's own earlier research) meaning "the hardware supports this but the vGPU-enabled driver isn't loaded right now." Collapsing these into one boolean would have been dishonest either direction - this session's own real P40 currently shows the second case exactly (hardware-capable, not currently active).

## What was built

`baseline/lib/gpu_admin.py`:

- `detect_gpus(runner)` - real `lspci -Dmmnnk` parsing (a real regex bug found and fixed by testing against *actual* captured output from this session's own machine, not an idealized guess: greedy matching left a trailing space in `pci_class`, caught immediately once tested against the real string) plus real sysfs-based render-node and kernel-driver lookups.
- `available_modes(runner, device)` - every mode with its own honest evidence string, computed fresh, never cached as a decision.
- Storage via `registry.py` directly (`TYPE_ID = "gpu_devices"`, `GLOBAL` scope) - not `settings_store.SettingDef`, for the same reason `network.py`'s interface aliases needed that: the set of GPUs is hardware-dependent and only knowable per real machine, not a fixed schema declared in advance. `GLOBAL` because "which mode this machine's substrate runs each GPU in" is a hardware fact about the machine, not a per-persona preference.
- `sync_detected_gpus` re-syncs a device's *definition* (hardware facts + current mode list) on every call without ever touching a previously-chosen `value` - a rescan can never silently discard an operator's prior choice.
- `set_gpu_mode` refuses a mode that device's own last-synced detection didn't mark available - real, per-device validation, never a "valid somewhere" check.

## Real bug found and fixed by grounding against actual hardware, not assumed formats

The `lspci` line-parsing regex was written first against a guessed format, then tested against this session's own real captured output (`0000:01:00.0 "VGA compatible controller [0300]" ...`) - it returned zero matches. Root cause: greedy `[^"]+` in the `pci_class` capture group consumed the trailing space before the class-code bracket, so `"VGA compatible controller "` (with a trailing space) never matched the exact-string filter against `_GPU_CLASSES`. Fixed by making the three text-capturing groups non-greedy. This is the same class of gap this project has caught repeatedly this session (a plausible-looking format that silently doesn't match real output) - caught immediately here specifically *because* the test was written against real captured text instead of a hand-typed guess.

## Verification performed

- 30 new tests, all using `lspci` output and sysfs scenarios matching this session's own real, previously-captured hardware data (two real GPUs: an RTX 3070 as a VGA controller with no mdev/sriov/toolkit, a Tesla P40 as a 3D controller with no *active* mdev but a known-capable PCI ID) - not synthetic/idealized fixtures.
- Real, non-test run of `detect_gpus`/`available_modes` against this actual machine, output matching the earlier manual investigation exactly (RTX 3070: host_display/vfio/virtio-gpu available, mdev/sriov/container-passthrough not; Tesla P40: vfio/mdev(hardware-capable)/virtio-gpu available, host_display/sriov/container-passthrough not).
- Real, non-test run of `sync_detected_gpus` against the actual `/mnt/BASELINE/registry/foundation.db` - confirmed both real devices land in the real database, correctly scoped GLOBAL.
- Full suite: 1452/1452 (1422 before this record).
- `gpu_admin.py` staged into `boot/provision.sh` proactively - `tools/check_provision_deploys_all_imports.py` doesn't yet flag it as required, since nothing imports it from a staged entry point yet (no web UI wiring exists), but it needs to already be in place the moment that wiring lands.
- **Not built yet**: any actual web/API surface to let an operator see and choose a GPU's mode (a "GPU Administration" page mirroring Drive Administration) - this record is the detection/storage layer only, per the agreed build order (finish this, then the `settings_store.py` per-group-registrar refactor, discussed the same session but not yet started).
