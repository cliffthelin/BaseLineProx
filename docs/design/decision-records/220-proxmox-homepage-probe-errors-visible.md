# DR220: Proxmox homepage probe errors stay visible

**Status:** Accepted  
**Date:** 2026-10-09

## Context

The VM creation page pre-fills the Proxmox GUI address from `vmbr0`. The
detector returned an empty string both when a successful probe found no usable
IPv4 address and when the `ip` command failed, returned malformed JSON, or
contained malformed address details. A failed observation therefore looked
like a valid unknown address and gave the operator no diagnostic.

## Decision

A failed command, timeout, malformed JSON, or invalid interface/address record
raises `VmError`. A successful, structurally valid probe with no usable global
IPv4 address still returns an empty value so the operator can enter the
endpoint manually. The VM page catches the detection error and displays it next
to the homepage field without hiding VM inventory and management controls.

## Evidence and scope

The combined Proxmox/QEMU VM host, VM page, and VM web suites passed 93 tests.
Command and JSON failures were injected; the web route used a local HTTP
fixture. No live Proxmox bridge, guest, or physical drive was inspected or
changed.

## Remaining work

The code now reports detection failures truthfully. A valid but address-less
bridge still requires the operator to enter a reachable Proxmox GUI endpoint;
this test evidence does not establish live guest connectivity.
