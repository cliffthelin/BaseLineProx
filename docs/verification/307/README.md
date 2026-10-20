# PC401 parity review

This directory records source review and restricted-session verification.
It does not claim that the physical PC401 is updated or bootable.

| Reviewed behavior | PC401 source result | Remaining evidence |
| --- | --- | --- |
| Serial-derived VG name, boot path rewrites | Imported; interrupted repair now resumable and cannot silently pass | Actual rename/reboot with a second drive attached |
| Wired NIC negotiation, modem exclusion, retry timer | Imported; Codex failure reporting and exclusive backups retained | Changed physical NIC, DHCP, internet |
| UAS quirks, USB port-specific checks | Imported | Actual enclosure stability and throughput |
| Persona routing and UUID fstab mounts | Imported | Two-drive mount identity and rebuild retention |
| Browser tabs, console link, persistent profile, startup retry | Imported | Visible native rendering and authenticated login |
| Proxmox storage names and private-LAN firewall rules | Imported | Effective configuration and inbound/outbound behavior |
| Existing-drive updater lane isolation | PC601 excluded before discovery/update | Guarded PC401 deployment |
| Default Ubuntu with five installed/configured apps | Not implemented in imported first boot | DR258 implementation and actual application launches |
| Root LV named SUBSTRATE; publishable substrate | Root still named `root`; publishability incomplete | DR257 implementation and privacy inspection |

Claude's shared-VG collision explanation is a plausible mechanism supported by
his changes and reports; this session did not independently reproduce the
physical freeze or prove that all freezes have that cause. His latest install
log (`baseline-build/pc601-install12.log`) ends with kiosk observed, QEMU exit 0
and `done: install, firstboot, kiosk`; those are recorded KVM/physical-target
installation results, not fresh native cold-boot tests by Codex.

Review fixes and their tests are documented in DR307. `focused-tests.txt`
records the 121-test result and scope; `vg-recovery-red.log` records the two
confirmed regression failures against the merged source. `full-unit-restricted.log`
preserves the full suite's unsuccessful restricted-session run without hiding
failures or weakening assertions. `runtime-access.json` and `pc401-preflight.txt`
identify the current deployment blocker.

For a host-capable continuation, start with the read-only command from this
checkout:

```sh
baseline/bin/baseline-allscript-install --target PC401 --stage preflight
```

Do not reuse `/dev/sdm` as identity; re-resolve serial `<PC401 drive serial>`.
Read `docs/INSTALL.md` and inspect current target use and verified recovery
before deployment. A destructive reinstall requires the operator's explicit
wipe command; no wipe command was executed or scheduled here. Keep the other
lane's processes, PC601 and build outputs intact.
