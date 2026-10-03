# DR130 VS Code configuration capture and fresh-profile verification

25 focused capture/HTTP/parser/subprocess/Node tests passed in2.23s. Synthetic
source documents, actual file I/O and CLI, no fake native installation proof.
live-vscode.json records actual installed Linux VS Code1.139.1 running under Xvfb
with a separate freshly staged profile and empty extension store. A temporary
development extension read actual workspace.getConfiguration values and quit.
All five settings matched; source fixture unchanged. Test-only telemetry/update
settings were added locally, not to the shared artifact. Existing user profile,
projects or account credentials were not read. No account login occurred.

This proves fresh-profile staging and real setting consumption, not clean binary
installation, VM/container migration/rebuild, isolation or cross-OS portability.
Spotify remains unimplemented. settings-artifact.json has approved synthetic
configuration only. recipe-page.html is source rendering, not a browser screenshot.
Node syntax, provision imports and whitespace checks passed. See DR130.

Final guarded regression suite: **2,945 passed in136.34s**. Runtime evidence
is specific to the actual local installed VS Code fresh-profile test above.
