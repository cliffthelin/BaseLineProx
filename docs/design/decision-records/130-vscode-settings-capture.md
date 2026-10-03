# DR130 — VS Code settings capture and fresh-profile staging

2026-10-02. Accepted. Partial queue76 application-specific extraction/apply.

## Implemented

VS Code is the first of the user-selected VS Code/Spotify examples. Web /recipes
Preview VS Code settings accepts a user-selected settings.json with comments and
trailing commas. Duplicate keys/malformed/oversized input and invalid supported
values refuse. Strings containing comment markers are preserved by lexical
parsing. Only editor.fontSize (integer6–72), editor.tabSize (integer1–16),
editor.insertSpaces, editor.wordWrap and files.autoSave are captured. Unknown
settings are counted and excluded without echoing their values or names. No
profiles, account tokens, projects, remote paths or databases are read.

Output baseline.vscode-settings/v1 is a configuration artifact, not an OS/app
installation recipe. The existing validated export control downloads only the
approved artifact. Sources/runtime installation remain explicitly unverified.
No automatic collection of arbitrary settings/profile contents is implemented.

New baseline-vscode-settings CLI provides capture INPUT and stage ARTIFACT TARGET.
Stage writes native User/settings.json under an exclusively new user-data directory,
with0700 directories/0600 file and file fsync. Existing destinations and redirected
ancestors refuse; no overwrite or automatic deletion. Missing parent/error/crash
leaves explicit failure/partial new target, never success. This is fresh profile
staging, not a mounted AppData identity check or guest installer. Provision copies
the module and CLI. No second installer/AI runtime dependency is introduced.

## Verification

TDD RED/GREEN: module absence, missing web preview, missing fresh-stage API and
missing CLI. 25 focused capture/web/parser/CLI/Node tests passed in2.23s. Fresh
profile I/O and source preservation use real filesystem; HTTP uses fixture
sessions, not native guest installation. Node syntax/provision/whitespace passed.

Actual installed Linux VS Code1.139.1 was launched under Xvfb with a separate
freshly staged profile and empty extension store. Temporary development extension
read workspace.getConfiguration and verified all five settings; it then quit.
Only synthetic source/configuration was used. Original user profile never read;
no account login. Test-only telemetry/update settings added locally and excluded
from shared artifact. No new binary install, VM/container, OS rebuild, physical
target writes or runtime isolation proof. Evidence: verification/130.

## Remaining work and record continuity

VS Code: verified source/package installation, versioned app recipe binding,
managed VM/container capture and apply, keybindings/snippets/extension locks,
reviewed richer settings, persistence ownership/isolation, rebuild/reset/restore
and cross-OS tests. Current five-setting preview does not make these complete.
Spotify: installation/source adapter, configuration classification/allowlist,
private-state boundaries and actual clean install/apply tests all remain open.
Its official Linux page states not actively supported; no universal OS claim.
Queues74/76 remain partial;59/60/75 recovery gaps and77 replacement restore remain
open. Current INSTALL/queue/handoff/planned-work updated; DR126–129 remain history.

Primary references: https://code.visualstudio.com/docs/configure/settings,
https://code.visualstudio.com/docs/configure/profiles,
https://code.visualstudio.com/docs/configure/command-line,
https://www.spotify.com/us/download/linux/ (checked2026-10-02).

Final guarded regression suite: **2,945 passed in136.34s**. Runtime evidence
is specific to the actual local installed VS Code fresh-profile test above.
