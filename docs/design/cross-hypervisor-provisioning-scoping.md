# Scoping: is a cross-hypervisor (cloud-init + Ansible) provisioning layer worth building?

Status: **scoped, not built.** This is a research/design pass with a
recommendation, not an implementation - matching the same kind of
outcome as `milestone-2-gui-plan.md` (Track B2).

## The question

`vm_provision.py`/`pct_provision.py` (decision records 34-35) are both
thin wrappers around Proxmox's own `qm`/`pct` CLIs - genuinely useful,
but locked to Proxmox by construction. The question raised in the
2026-09-26 design review: is that lock-in acceptable, or should
Baseline build a provisioning layer that would also work if the
substrate were ever something other than Proxmox?

## What the alternative would actually be

**cloud-init** is not itself a provisioning tool - it's the
in-guest first-boot configuration mechanism almost every cloud/VM
image already ships with (Baseline's own Track B3 QEMU proof used a
stock Debian cloud image and hit cloud-init behavior directly, per
`tools/testpersistence_phaseB_vertical_slice.py`'s comment about a
cloud-init-related bug it had to sidestep). It answers "once the VM
exists and boots, how does it configure itself" - hostname, SSH keys,
users, packages, an arbitrary `runcmd` script - via a `user-data`
file, hypervisor-agnostic by design.

**Ansible** answers a different question: "how do I converge a fleet
of already-existing machines (VM, container, or bare metal, on any
hypervisor or none) to a declared state," over SSH, agentless.

Neither one creates a VM or container - that's still `qm create`/
`pct create` on Proxmox, `virt-install` on plain KVM/libvirt, or a
cloud provider's own API elsewhere. The actual cross-hypervisor
architecture would be: keep a thin, swappable "create the guest" step
per substrate (Proxmox today, something else later), and move
everything above that line - what the guest becomes once it exists -
into cloud-init `user-data` + an Ansible playbook, so *that* half
never has to be rewritten if the substrate under it ever changes.

## Why this project's constraints point away from building it now

- **Proxmox is the stated substrate, not an implementation detail
  Baseline is hedging against.** The whole architecture (`baseline-
  firstboot.service` taking over tty1, the kiosk GUI onto Proxmox's
  *own* web UI, `sensors_history.py` reusing Proxmox's *own* RRD data)
  is built assuming Proxmox is there. A cross-hypervisor abstraction
  defends against a substrate change nothing in this project's own
  documented direction anticipates.
- **YAGNI, concretely, not just as a slogan.** This project's own
  coding-style rule is explicit: don't build for a requirement that
  isn't real yet. Today there are exactly two provisioning primitives
  in this repo (`vm_provision.py`, `pct_provision.py`), both new, both
  unverified on real hardware, both Proxmox-native. Adding a second,
  abstracted layer on top of code that hasn't even had its first real
  round trip yet is exactly the premature-generalization case that
  rule warns about.
- **Ansible needs something this project has deliberately not built
  yet.** Agentless Ansible needs SSH reachability into every managed
  guest as a base assumption - fine for A4's example VMs, a real
  design question for anything meant to run unattended before a
  network is configured (the same territory `firstboot_statemachine.py`
  already treats carefully). Adopting Ansible now would mean solving
  that alongside everything else, rather than in its own pass.
- **The actual near-term risk is different.** The two modules built in
  items 34/35 are unverified against real hardware - that's a nearer,
  higher-value verification gap than portability to a substrate this
  project isn't currently planning to leave.

## Recommendation

**Don't build a cross-hypervisor abstraction now.** Two narrower,
lower-cost things are worth doing instead, whenever there's a real
guest to configure post-creation (not before):

1. **Use cloud-init's `user-data` for in-guest first-boot config**,
   independent of any bigger abstraction - it's already present in
   every cloud image this project uses, costs nothing to reach for,
   and is the natural place to put a new VM's "configure yourself"
   step once `vm_provision.create_vm` actually needs one (it doesn't
   yet - it stops at booting an install ISO, matching Track A4's own
   scope).
2. **Revisit Ansible specifically if and when a *fleet* of guests
   needs converging to a shared state** - one VM configuring itself
   via cloud-init doesn't need it; several guests staying in sync
   over time is the actual trigger this tool solves for, and that
   need doesn't exist in this project yet.

If Baseline's substrate assumption ever genuinely changes - a real
decision, not a hedge - that's the point to build the abstraction
layer described above, informed by whatever the new substrate actually
is, rather than guessing its shape now against a substrate change that
isn't planned.

## Not decided here

- Whether Baseline itself is ever offered as an installable target on
  a non-Proxmox hypervisor - a much bigger question than provisioning
  tooling, out of scope for this document entirely.
- Any specific cloud-init `user-data` template or Ansible playbook -
  neither exists yet and neither is proposed by this document as
  something to write speculatively.
