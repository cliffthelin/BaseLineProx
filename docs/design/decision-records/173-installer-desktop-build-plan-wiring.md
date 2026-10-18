# DR173 — Connect Installer desktop choices to the saved build plan

2026-10-08. Continues DR172 and queue72/74/75/76/78.

The Installer desktop previously persisted icon placement and per-environment
display settings without applying the selected drive, OS, application, or
application configuration to the canonical Installer Plan. That disconnect
made the desktop look like a build configurator when its choices did not reach
the existing installation workflow.

Drive shortcuts now resolve against fresh discovery. Protected drives are
disabled and explain preservation; selecting an eligible drive updates the
serial used by the existing reviewed update workflow. OS shortcuts save the OS,
variant, and active environment name to the Installer Plan draft. Application
shortcuts add the application to the build draft, and their settings modal saves
captured configuration alongside the application choice. The environment modal
continues to identify every environment as a draft until a real provision job
reports success. These changes only save plan choices; installation remains
behind the existing review, human confirmation, and native authorization gates.

## Verification

Real Chromium/HTTP integration verifies active environment naming, the six-block
settings modal, protected-drive refusal, eligible-drive serial selection, OS
selection, app selection, and app configuration saved into the canonical plan.
Focused Installer tests pass 22; `git diff --check` passes. Test device
discovery and privileged execution are synthetic. During this session, sysfs
block inventory identified PC401 `<PC401 drive serial>` and PC601
`<PC601 drive serial>`, but this execution namespace exposed no `/dev/sdb` or
`/dev/sdc` device nodes. No physical write, Proxmox boot, firewall/network, or
overlay persistence check was run. No physical behavior is claimed verified.

Full installer Build/Rebuild, multi-workload composition, installed-system
runtime, native cold boot, LAN/firewall, universal driver packaging, and
physical USER_PERSISTENCE/APPDATA routing remain open under queue72/74/75/76/78.
DR173 documents this bridge; it does not close those acceptance requirements.
