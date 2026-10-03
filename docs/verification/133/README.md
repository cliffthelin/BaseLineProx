# DR133 verification

Actual native application and retained OS-root rebuild evidence, 2026-10-03.
This is disposable KVM/Proxmox evidence, not physical deployment.

`source-locks.json` contains the five actual publisher locks. HTTPS/SHA256 are
verified; no detached signatures or complete system dependency lock. The exact
versions are VS Code1.140.0, Spotify1:1.2.95.453.g0eeebbed,
Chrome154.0.8037.97-1, ChatGPT26.930.31730, Claude2.9939.4.

`debian-retained-result.json` records the stopped, pre-launch comparison after
replacing the Debian OS root and reinstalling through the actual suite CLI.
All five identities and30,827 inventoried regular files match. It excludes
transient IPC/Singleton files and regenerated ChatGPT .codex/tmp. These profiles
were unauthenticated; most ChatGPT files were its generated runtime SDK.

`debian-native-windows.json` records all five post-rebuild native windows.
Reviewed PNGs show actual VS Code, native ChatGPT, native Claude, corrected Chrome
homepage and the Claude callback/public ChatGPT browser proof. Spotify's login
screenshot is deliberately unpublished because it includes a generated login QR.
Its login UI was inspected locally; a window title alone is not rendered-UI proof.

`filesystem-boundary.json` records actual Debian namespace checks: own home
visible/writable, other private home absent, code read-only, inherited host
variable absent and exchange visible only with an explicit grant.

`browser-uri.json` records Claude's public website/native action dispatch and
refusal of a cross-app callback and file URI (exit codes0,0,1,1). Browser profile
is private to the requester. No authenticated OAuth, playback, chat, keyring
migration, cloud backup or replacement-device recovery was tested.
Chrome reaches the real Proxmox endpoint but shows its untrusted-certificate
screen. No TLS bypass flags were added. Human trust acceptance remains open.
Ubuntu24.04.5 separately reopened all five with backed-up/restored private data;
Debian13.7 received the full fresh-root rebuild. Both are virtual test guests.

TDD RED/GREEN covers source locks/acquisition, native extraction, capacity,
namespace command construction, private backup/restore, bus policy, native
capture/apply, suite composition/build, scoped URI handler, admin helper update,
CLI argument parsing and desktop entry generation. Current-source full suite:2,979 passed in122.77s; focused29 passed.
An overlong AF_UNIX fixture path initially failed; binding the same real socket
relative to its directory fixed the fixture without weakening socket/FIFO checks.
No source packages, disk images, private profiles, credentials, cloud seeds or
QR screenshots are included in publication. `.runtime-proof133` remains local.

Primary availability/install references reviewed for this implementation:

- [ChatGPT Linux preview](https://learn.chatgpt.com/docs/linux/linux-app)
- [Claude Desktop installation](https://support.claude.com/en/articles/10065433-install-claude-desktop)
- [Spotify Linux](https://www.spotify.com/us/download/linux/) — Linux is not actively supported by Spotify.
- [Google Chrome prerequisites](https://support.google.com/chrome/answer/95346)
- [Debian publisher cloud images](https://cloud.debian.org/images/cloud/trixie/latest/)

Native preferences export/apply is limited to five VS Code settings and Chrome
homepage. The other three portable recipes currently expose Baseline scale only;
full private native state survives as a retained home, not a configuration recipe.
