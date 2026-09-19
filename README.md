# Baseline V0.1

From a disposable USB-C SSD: boot a Proxmox-based host, land at a Baseline
prompt on TTY1 with deterministic hardware status, bring networking up with
clear diagnostics (including USB-tether fallback), and reach a cloud LLM
through a harness constrained to Baseline's own read-only tools.

Full requirements, architecture, and open questions live in the
[vertical-slice PRD](https://claude.ai/code/artifact/6b5c2489-b3fc-4986-baf3-0c109d3a9296).

## Salvage boundary

This project has a precursor (`cliffthelin/baseline_os`, plus a physical
precursor USB stick). `docs/salvage/OLD_BASELINE_NOTES.md` documents what was
learned from it — **no source files from that project are copied into this
repo.** Contributors should not reach back into the old tree for code; if a
pattern from it seems useful, describe it and reimplement it here.

## Layout

- `boot/` — Proxmox integration (`provision.sh`) and the `baseline.service`
  systemd unit that gives Baseline tty1.
- `baseline/` — the Baseline app:
  - `lib/hardware.py` — Step 4, Hardware Contract (inxi collector, normalized
    schema, snapshot/diff).
  - `lib/network.py` — Step 5, Lifeline Networking (staged observed-state
    facts: NIC → driver → carrier → address → gateway → DNS → internet →
    LLM provider).
  - `lib/harness.py` — Step 6, Read-Only Harness (Claude Code CLI, zero
    tools, Baseline's own context handed in as text, no tool-calling
    surface at all).
  - `bin/baseline` — Step 3/7, the Core CLI + Rich-rendered output.
  - `bin/baseline-auth-setup.sh` — guided one-time AI account setup: runs
    `claude setup-token` interactively, captures the resulting credential
    itself, writes it to `/etc/baseline/harness.env` (0600) — the operator
    never hand-copies a token anywhere.
- `docs/salvage/` — what was learned from the old Baseline project (notes only).
- `docs/adr/` — architecture decision records.

## Status (V0.1 vertical slice)

Steps 1–7 are built and proven live under QEMU on two separate Proxmox
installs (run in parallel as dev/test capacity): tty1 ownership, deterministic
hardware, staged network diagnostics, and a working read-only harness
answering real questions from real machine state via a Claude subscription.
Not yet done: the bare-metal boot test, the USB-tether fallback path (needs
real USB hardware, untestable under QEMU), and running the full
plug-in → boot → hardware → network → ask → pull-Ethernet → diagnose →
tether → recover demo as one continuous sequence.

## Provisioning

`boot/provision.sh` turns a fresh Proxmox VE install into a Baseline host:
disables the enterprise repos (no subscription assumed), installs `inxi`,
`python3-rich`, Node.js 22 (via NodeSource — Debian's own package is too
old for Claude Code), and Claude Code itself, deploys the app, and installs
the systemd unit. Run it as root, then run `baseline-auth-setup.sh`
separately and interactively (it needs a real login to complete OAuth).

## Non-goals for V0.1

VM launch, GPU passthrough, full VAULT (LUKS/pairing/trust), and the Phone
Rescue Channel are all deferred to v0.2+. See the PRD's Non-Goals section.
