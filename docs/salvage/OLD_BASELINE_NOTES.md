# Old Baseline — Salvage Notes

Reference notes only. No source files from the prior project are copied into this
repo. Everything below is a paraphrased summary of patterns and decisions found in
two places:

- A physical precursor USB stick (`BASELINE1` boot partition + a locked `VAULT`
  LUKS partition) — inspected read-only by extracting its `initrd.img`.
- The public source repo, [cliffthelin/baseline_os](https://github.com/cliffthelin/baseline_os)
  (README + `docs/archive/BASELINE_OS_PRD_0.MD`).

Full architectural reasoning behind each of these lives in the
[Baseline V0.1 vertical-slice PRD](https://claude.ai/code/artifact/6b5c2489-b3fc-4986-baf3-0c109d3a9296).
This file is the durable, in-repo version of that "what we're keeping vs. not"
boundary so it survives independently of any single doc/session.

## Lineage

`GRUB_ASSIST` (bash menu recovery toolkit) → `Boot_Assist` → `AntiGravity OS` →
`BASELINE_OS`. The original PRD's stated goal was zero GPU dependency
(framebuffer/KMS only, no X11/Wayland) and static-binary tool bundling
(`ddrescue`, `testdisk`, `chntpw`, `cryptsetup`) inside a custom initramfs,
originally against a single Gemini API backend before a multi-provider registry
was added later.

## Patterns worth keeping (as ideas, reimplemented fresh)

- **`boot_event` JSONL logging contract** — one structured record per boot step:
  `component, step, status (pass|fail|start|timeout), required, impact, next_step,
  duration_ms, detail`, plus a correlation `boot_id` and build fingerprint. Clean
  "what failed / does it matter / what happens next" schema — reuse the shape for
  both boot and network diagnostics.
- **`run_step`/`failsafe` wrapper convention** — every boot action gets a timeout,
  a status line, and a matching log/event entry; a hard failure drops to a shell
  rather than hanging, and boot modules are *sourced, never exec'd*, so one
  module's failure can't kill PID 1.
- **`inxi --output json` + snapshot/diff** — cheap, real hardware-drift detection
  (`detect_hardware_changes()`): snapshot each boot, diff against the last one,
  classify severity, surface recommendations. Keep the pattern; don't make `inxi`
  itself the API (see PRD Step 4 — Hardware Contract).
- **`AIProviderRegistry` / `AIProvider` ABC shape** — pluggable AI backends behind
  one interface. Reuse the *shape* for a `HarnessAdapter` contract; the old
  implementation just shelled out to CLI tools, which V0.1 does not repeat.
- **`pair_and_trust_device()`** (Bluetooth-scoped) — naming/flow template for
  device pairing+trust, relevant whenever V0.2 revisits VAULT or phone pairing.
- **`INSTALL_STRATEGY.md`'s 4-tier model** — offline core → Vault handoff →
  online hydration → snapshot. Independently confirmed as a *shipped* feature in
  the GitHub README (Tier 1–4, "💧 Hydrate" button), not just a design doc.
- **StartupManager's 6 named health checks** (AI API Key, Vault Security,
  WiFi/LAN, Boot Config, AntiVirus, Disk Health) — a concrete, queryable
  diagnostics-to-AI handoff pattern, more specific than the raw boot log alone.
- **Test runner scripts** (`tests/run_qemu_*.sh`, `run_virtualbox.sh`,
  `run_gnome_boxes.sh`) — a real integration test suite existed in source
  (`test_vault_integrity.py`, `test_persistence_unlock.py`,
  `test_agentic_execution.py`, `test_startup_manager.py`, `tests/integration/
  verify_*.py`). It just never shipped inside the built `initrd.img`, which is
  why the extracted boot image showed none of it. Model V0.1's own test strategy
  on this runner-script pattern.

## Explicitly NOT carried forward

- The custom initramfs/kmscon boot stack — V0.1 boots via stock Proxmox VE
  instead of authoring its own `/init`.
- The single hardcoded `BASELINE_MOCK` mock-data fixture as a testing strategy.
- The two never-unified "vault" concepts: a boot-diagnostic scratch mount named
  `VAULT_MNT` (snapshot/restore/undo tool) vs. an "encrypted Vault" design concept
  that was never wired to a LUKS unlock at boot. V0.1 treats VAULT (when V0.2
  gets there) as one first-class entity from the start.
- The hardcoded-`wlan0`, no-Ethernet-automation, no-tether Wi-Fi script.
- The "Agentic (YOLO)" AI mode — the old harness could propose *and, with
  approval, execute* bash commands. V0.1's harness is read-only tools only; this
  is a deliberate narrowing, not an oversight.
- Picking a specific cloud LLM provider as part of the architecture — the old
  registry existed to swap CLI tools; V0.1 defines a `HarnessAdapter` contract so
  the provider is an implementation detail, not a design decision.

## Out of scope, do not touch

`VAULT1`'s `vault.img` (LUKS-encrypted, ~25GB) on the precursor stick is locked
and its passphrase is unknown. It is evidence the old project reached the VAULT
idea and stalled on the boot-time unlock path — not a template to copy, and not
something to attempt to open.
