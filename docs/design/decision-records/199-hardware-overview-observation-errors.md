# DR199 — Hardware overview reports failed observations

Date: 2026-10-09

## Decision

The Hardware overview must query a real `RealRunner` when no runner is supplied.
Unavailable or failed observations are not replaced with generic `Linux`, empty
inventory, or `None` without explanation. Host fact collection now retains each
successful fact and returns source-specific errors for failed `uname`,
`/etc/os-release`, `/proc/cpuinfo`, `/proc/meminfo`, default-route, dependency,
sensor, NVMe, SMART, and hardware-inventory probes. The page renders those errors
as an alert. Missing values remain missing; they are not inferred.

## Evidence and limits

The regression tests first failed against the previous empty-return path. After
the change, 116 focused Hardware web and truthful-runtime tests passed. The
no-runner case injects a recording FakeRunner to prove the real collection path
is entered; failure tests inject probe errors and confirm that each appears in
the rendered page. This is unit evidence only, not a claim that every probe
succeeded on physical hardware. Other runtime observation consumers remain in
REAL-006.
