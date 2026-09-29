# Decision record: GPU device wiring on `quadlet.py`'s `ContainerSpec`

Status: **implemented, unit-tested (1465/1465 full suite, up from 1454), verified for real - resolves this session's own Tesla P40/RTX 3070 to their real CDI identifiers and generates a genuine, ready-to-write Quadlet unit.**

## What was asked

Continuation of the v0.2 queue, item 19: give `quadlet.py`'s `ContainerSpec` a way to hand a container real GPU access, using `gpu_admin.py`'s (decision record 94) already-built detection rather than a raw, hand-typed device path.

## What was built

- `quadlet.ContainerSpec.gpu_devices: list[str]` - real, already-resolved device strings, rendered as `AddDevice=<value>` lines in the generated unit. Deliberately takes plain strings, not a `gpu_admin.GpuDevice` object - matches this module's existing design for `volumes`/`network`/`publish` (a pure generator that never resolves anything itself, the caller supplies already-real values).
- `gpu_admin.resolve_container_devices(runner, device)` - the actual resolution logic, kept in `gpu_admin.py` rather than `quadlet.py`, so `quadlet.py` stays free of any GPU-specific knowledge:
  - Non-NVIDIA: the device's own render node (`/dev/dri/renderD*`) - genuinely sufficient, no vendor runtime needed.
  - NVIDIA: a real CDI device identifier (`nvidia.com/gpu=<uuid>`), resolved via `nvidia-smi --query-gpu=pci.bus_id,uuid` - not asserted, verified per-device by matching PCI address. Falls back to the render node alone (graphics-only, not full CUDA capability) when `nvidia-smi` can't resolve one, rather than emitting an unverified CDI string.

## Real bug found and fixed: PCI domain digit-count mismatch

`nvidia-smi --query-gpu=pci.bus_id` reports an 8-hex-digit PCI domain (`00000000:01:00.0`); `lspci` (and `gpu_admin.py`'s own `pci_address`) uses a 4-hex-digit domain for the exact same real device (`0000:01:00.0`) - confirmed directly on this session's own hardware, not assumed. A naive string-equality match between the two would silently never match. Fixed with `_pci_suffix()`, which normalizes both to their trailing `bus:device.function` component before comparing - verified against this exact real mismatch, not a synthetic case.

## Verification performed

- New tests: 4 in `test_quadlet.py` (device lines render correctly, including multiple devices and the none-configured case), 8 in `test_gpu_admin.py` (`_pci_suffix` domain normalization against the real mismatch, `_nvidia_cdi_device` resolving the real UUID and returning `None` cleanly when unresolvable, `resolve_container_devices` for NVIDIA/non-NVIDIA/no-render-node cases).
- Real, non-test verification against this actual machine: `resolve_container_devices` correctly resolved both the Tesla P40 and RTX 3070 to their real, distinct CDI UUIDs (matching `nvidia-smi --query-gpu=pci.bus_id,uuid`'s own live output), and `quadlet.generate_unit` produced a genuine, well-formed `.container` file with the P40's real `AddDevice=nvidia.com/gpu=...` line - ready to write and start, not just asserted correct from the code.
- Full suite: 1465/1465 (1454 before this record).
- **Not verified**: no container has actually been started with this device wiring against real Podman + the NVIDIA Container Toolkit's own CDI-spec generation (`nvidia-ctk` isn't installed on this machine, confirmed in decision record 94) - the CDI *identifier* is real and verified; whether Podman itself successfully honors it at container-start time on this host has not been observed.
