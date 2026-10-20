# DR314 — FydeOS VirtIO display and retained appliance disk

2026-10-19. Supersedes DR267's conclusion that this FydeOS image requires
Intel GPU passthrough. That earlier test observation remains historical.

The operator asked to focus on getting FydeOS working. Inspection found the
shipped kernel includes a VirtIO GPU module and a built-in VMware driver. The
VMware driver rejects QEMU's incomplete SVGA device (missing pitchlock), while
the VirtIO module was not loaded before display startup. This is not an absence
of virtual display drivers.

## Reproducible preparation and VM behavior

`baseline-build-os-base build --os fydeos` verifies the appliance's internal
VMDK checksum, converts a disposable regular-file copy, and adds early
`modprobe virtio_gpu` and `modprobe virtio_net` calls to its existing early udev
job. It checks the edited file before updating ROOT-A. The vendor appliance,
its account/state partition and carried OVA are unchanged. No credentials,
account or debug shell are added. Outputs are compressed qcow2 and a checksum
manifest. A newly built manifest explicitly says runtime is unverified; the
successful display rehearsal is recorded separately for the tested output.

FydeOS uses UEFI, SATA, e1000 and VirtIO 3D/virgl with a working host EGL render
node. Non-3D VirtIO reaches the splash but Chrome cannot initialize EGL. The
launcher now permits a prepared base rather than categorically rejecting
FydeOS; installation rejects the old unprepared manifest. The default 50 GiB
disk matches the appliance. Proxmox registration selects SATA, e1000 and
virtio-gl and disables the nonexistent guest agent. These Proxmox commands
are unit-tested with an injected runner, not executed on native Proxmox.

The complete writable appliance disk goes in the host's protected user disk
store, since FydeOS holds account state in that disk. It has no disposable
OS rollback and does not pretend to consume the generic retained-home seed.
Retirement still checks exact owned attachments, including its SATA slot,
and rejects additional foreign disks. Prepared generic FydeOS output is stored
on APPDATA_ADMIN/os-bases, outside vanilla INSTALLER_CACHE; existing sources
for other operating systems are unchanged.

## Evidence and limits

Real QEMU/KVM, NVIDIA host render node /dev/dri/renderD128: the clean image
rendered language selection and welcome; VNC clicks changed the visible screen.
After a QMP reset it rendered setup again. No terms were accepted, no account
was created and no account retention, Android/Linux subsystem, five default
applications, or provider credentials were verified. Network was restricted;
the terms page in the exploratory VM showed a DNS error, which is not internet
acceptance evidence. Nothing here proves a native PC601 Proxmox boot.

Clean base SHA256:
`91a7817a8df8b85a2355944de988ace54c83e211c5d27c14663ecee48b8bc3b0`.
The same hash was checked after booting the retained copy; the base was untouched.
Build and rehearsal artifacts are under CACHE/baseline-build/fydeos-repair;
visible welcome evidence is docs/verification/314/fydeos-clean-welcome.png.
The exploratory debug files are separate and are not the prepared base.

Source: failing tests confirmed before each implementation step. Focused
builder, profile, factory, lifecycle and Proxmox tests pass. Native execution,
working host render-node provisioning, owner-completed onboarding, application
integration and account retention belong to queue72/78 and remain open.
Living INSTALL and the work queue are updated; DR267 is left as history.

Vendor support boundary: the appliance is officially supported only on VMware;
Baseline's QEMU compatibility is independently rehearsed and not vendor support.
See https://fydeos.io/help/knowledge-base/installation-guides/fydeos-for-vmware/fydeos-for-vmware/ .
