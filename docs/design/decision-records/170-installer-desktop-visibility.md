# DR170 — Make the requested Installer desktop visible

2026-10-07. Supersedes DR169's default-view behavior; preserves its controls and
physical verification boundary.

The operator reported that the requested features were not visible on Installer
Plan. The additional mode defaulted to Current workspace and its taskbar was
collapsed. No owner-scoped display preference was present in the live store at
inspection. The earlier report that the mode was loaded did not establish that
the operator could actually see it. This was a discoverability defect.

Fresh layouts now default to Phone desktop & taskbar with its icon row expanded.
Current workspace remains selectable, and saved choices remain honored. A direct
Installer desktop menu entry opens /install-plan?display=desktop even when a
workspace choice was saved. Explicit selector changes clear that override from
the URL and persist normally. No automatic drive operation is attached to this
URL; the earlier continue_serial behavior remains separate.

Confirmed RED then GREEN: first-load desktop visibility, direct menu entry and
direct URL overriding a saved workspace choice. The full Chromium mouse/touch
and configured-object interaction script passed. 100 focused HTTP/configuration
regression tests passed. Browser proof uses synthetic privileged commands and
disk identities; no physical drive update or boot is claimed.

The actual native read-only discovery/autofill/catalog pipeline returned two
drives and five applications with environment fields name/os/variant. A sandbox
boot-identity refusal was treated as inconclusive and checked natively, not
reported as absent hardware. The real server was reloaded and the explicit
desktop URL opened in the existing browser. Operator-screen acceptance remains
for the operator to observe; opening a URL is not a screenshot of their screen.

INSTALL status and handoff are corrected; DR169 is retained as history.
Physical and generalized workload/driver acceptance remains open under
queue72/74/75/76/78.
