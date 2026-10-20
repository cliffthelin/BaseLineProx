# Configuration web application checklist — 2026-10-04

Evidence and boundaries: DR149, DR150, DR151 and DR154. Production operations must use the web app;
fixture runners are permitted only in tests.

- [x] Shared styled header for all existing tabs.
- [x] Options-first nested settings; optional collapsed JSON override.
- [x] SMART/network known-value selectors and explanations; compact numeric inputs.
- [x] Settings/Admin autosave with actual response status and existing elevation gate.
- [x] One Operations action form, schedules and audit-backed run history.
- [x] Remote access current SSH/firewall configuration before observed results.
- [x] Hardware host/managed-VM target selection, category sub-tabs, serial-based Drive Administration links, observed driver package ownership and associated catalog packages (DR151); existing real driver load handler.
- [x] App Isolation tabs, search and paged category trees.
- [x] Replace old Master Config page with current owner-backed settings, policy and storage sections; search/filter.
- [x] Persist installer/recipe drafts and aggregate them in Master Config (DR150): owner-scoped SQLite records, autosave/restore, revision conflict detection; saving never applies a draft.
- [ ] Edit VM, container, operator and schedule configuration directly within Master Config with their native validation.
- [ ] VM device model/passthrough configuration and supported guest driver installation, with real verification.
- [ ] Installer Cache real file links/downloads, all publisher sources and safe acquisition/check/update/install actions.
- [ ] Applications page with installer provenance and Hardware/Applications cache associations.
- [ ] Remote access Tailscale policy configuration/actions beyond observed status.
- [ ] Remove remaining per-VM save buttons and use correctly verified job-aware autosave.
- [x] Browser Hardware category switching, keyboard navigation, package links and matching serial-drive navigation (DR151).
- [ ] Browser interaction checks for Operations and large App Isolation trees.
- [ ] Complete PC401 post-rename disk boot and native boot proof after mount recovery, using production web workflow (DR146, queue78).

- [x] Optional Diagnostics save without execution; separate authenticated manual Run with chosen peer/port and real firewall/listener/measurement checks (DR154). Actual HTTP and Linux backend verified without FakeRunner; successful browser-submitted active traffic remains unverified.

- [x] Actual Ethernet/AP/Wi-Fi throughput on TCP 5201 with negative loopback control, hardware counters and independently observed temporary-resource cleanup (DR156). Separate-host and browser-submitted active tests remain open.

- [x] Web installer input preparation from saved owned draft, immutable code/configuration bundle, real missing-input report and source-only job inspection (DR158); no installation execution.
- [ ] Complete all seven installer outcomes tracked in [installer-acceptance-checklist.md](installer-acceptance-checklist.md).

- [x] Ubuntu publisher-pinned source acquisition as a durable web job, typed selector, actual-file link and base-provenance checks (DR159); detached signatures and other installer sources remain open.

- [x] Restart host authentication survives production web reloads with HMAC-protected hashed-token session records; expiry offers a same-origin sign-in link, and logout revokes sessions (DR160). Native restart remains separately user-confirmed and not physically verified by tests.
