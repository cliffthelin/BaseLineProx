# DR303: PC401 acceptance checklist progress

**Date:** 2026-10-11  
**Status:** one safety subcheck complete; physical acceptance open

## Completed subcheck

The Codex QEMU process named `pc401-e1000e-serial-bound-overlay` is stopped.
`qemu-img check` on
`/mnt/10TB/backup/baseline-tests/pc401-e1000e-20261011-045012/pc401-physical-serial-overlay.qcow2`
reported no errors. This validates the overlay's structure and confirms that
the prior Codex test process is not still running.

## Limits and next steps

This does not establish the PC401 VG's host use-state, authorize another
raw-backed QEMU attachment, or prove a native boot. Resolve host LVM/use state
through the approved application path, and disconnect PC401 from the
development host before native testing. Continue the ordered acceptance
checklist in `docs/INSTALL.md`: native boot, network/internet, firewall, GUI
login, VM/container operation, distro/application and driver readiness, and
overlay/user-persistence retention through restart and rebuild.
