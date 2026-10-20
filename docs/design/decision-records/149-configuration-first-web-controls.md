# DR149 — Configuration-first web controls and combined Master Config

Accepted 2026-10-04, direct operator instruction. Supersedes DR83's standalone
Master Config rendering and dashboard-oriented layout, not its authentication.

Settings use typed controls, compact numbers, known-option selectors and inline
help. Nested configuration uses repeatable controls; JSON is a collapsed,
explicitly enabled override. Changes use existing authenticated save routes and
show actual application/refusal results. Admin controls stay disabled until real
elevation. Shared shell styling covers the previously unstyled tabs.

Operations has one action selector, changing description/parameters, one run
form, schedules and durable audit-backed history. Remote access leads with its
current SSH/firewall configuration; observed listeners are secondary. Hardware
lists devices and installed compatible driver candidates, with actual modprobe
and a re-read of binding status. Managed VM driver inspection requires a real
guest execution adapter; unsupported adapters report an error. No driver load
or real host setting change was executed as validation.

Application isolation uses category tabs, search, grouped trees and fifty-item
pages. Its policies remain declared plans, not proof of enforcement. Rendered
application details escape dynamic values before browser insertion.

Master Config now reads current Settings and effective Admin settings, schedule
storage, managed VM/storage configuration, container storage, operator roles,
installer catalog and declared app isolation policies from their owning sources.
Search and section filters apply to the single long page. Settings/Admin edits
reuse their existing handlers. Other configuration is displayed with an owning
tab link; it is not editable in the combined view yet. Hardware bindings are
observed rather than persisted settings. Recipe/installer browser drafts have
no persisted draft source for aggregation, stated visibly. Operational logs and
approvals are records, not editable settings. Credentials are not included in
VM rows; only an explicit configuration-key allowlist is rendered.

Verification: focused Python contracts plus real local HTTP routing tests;
278 tests passed before the added Master Config HTTP test, which then exposed
and corrected a handler token accessor error and passed independently. Real
Chromium verified rendered configuration editing, autosave, compact controls,
help, overrides, elevation locking, plan/recipe selectors and Master Config
search/filter against isolated configuration fixtures. Fixture writes and fake
runners are test-only; this is not physical storage or real VM driver proof.

Remaining work is tracked in configuration-web-checklist.md. Physical PC401
boot verification remains open under DR146; nothing here resolves its pinned
mounts, reboots the host, or modifies either physical target drive.

Deployment: reloaded the existing desktop web process, preserving its environment
and configuration. GET /login returned HTTP200 with Referrer-Policy same-origin.
The reload resets in-memory sessions; the operator must log in again.
