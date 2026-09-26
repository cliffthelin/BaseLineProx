# Milestone 2 GUI investigation plan

Status: design doc (Track B2 of `zazzy-noodling-music.md`). Answers the open
questions Track B1's inventory found unresolved before B3's disposable QEMU
proof is built. Pragmatic choices for this milestone's scope, not claimed as
final production answers - the same discipline Track A2 used for its own
open PRD questions.

## B1 recap - what already exists

- `baseline/lib/settings_web.py` - a complete, tested, LAN-scoped settings
  HTTP server. Confirmed still completely dormant: `grep -rln settings_web`
  across the whole repo returns only its own test file. No systemd unit, no
  `bin/` launcher references it anywhere.
- `docs/design/drive-setup-gui-v2-prd.md` - a GTK4 *installer* framework PRD,
  still draft, about the pre-install wizard, not the post-install kiosk GUI
  this milestone is about.
- `bin/baseline`'s Chat tab - a plain Textual `Log` widget fed by the AI
  harness. No PTY embedding, no browser, no compositor - confirmed by direct
  inspection, not assumed.
- TestPersistence's own decision record 29 established this project's grant-
  broker philosophy for a different domain (disk access): small, explicit,
  kernel-enforced-where-possible boundaries with real `authorize()`/revoke
  gates, never a generic all-purpose broker daemon. This milestone's four
  GUI brokers follow the same minimalism, not a portal framework's full
  surface.

## Compositor: `cage`

Same choice as Track A3, for consistency - and now a *proven* choice, not a
guess: Track A3 installed `cage` 0.2.0-2 + stock `chromium` from Debian
trixie's own repos on the real Track A1 hardware, wired it to a dedicated
VT via the exact `TTYPath`/`Conflicts=getty@ttyN.service` pattern already
used by `baseline-firstboot.service`, and verified via a genuine reboot that
it renders correctly with zero manual intervention.

One real finding from that proof, applicable here too: `cage`'s renderer
refuses to start against a GPU-driver-less virtual display (`bochs-drm`,
this project's own QEMU environment) unless `WLR_RENDERER_ALLOW_SOFTWARE=1`
is set to allow its software-rendering fallback. B3's disposable QEMU proof
will hit the same environment and needs the same environment variable.

## Browser packaging channel

Stock Debian `chromium` package (same as A3) - not a Flatpak, not an
upstream `.deb`, not a custom build (explicitly out of scope per the user's
own earlier answer). Debian's package already respects the standard
Chromium enterprise-policy path (`/etc/chromium/policies/managed/*.json`),
which is what "browser launch under a generated policy" (B3's exit
criterion) means concretely - see below.

## Portals: a minimal Baseline-owned broker layer, not the full `xdg-desktop-portal` stack

`xdg-desktop-portal` is designed for sandboxed apps (Flatpak, etc.) talking
to a portal daemon over D-Bus, with backend implementations
(`-wlr`, `-gtk`, `-gnome`) providing the actual UI. Two reasons not to adopt
it wholesale for this milestone:

1. **Scope mismatch.** `-wlr`'s backend is built around screenshot/screencast,
   not the four capabilities this milestone actually needs
   (notification, clipboard, file-picker, download/export). `-gtk` covers
   more of them but drags in a GTK/GNOME service surface disproportionate to
   one kiosk browser.
2. **Trust model mismatch.** This project's own established pattern (grant
   broker, `repair.py`'s Runner mediation, `settings_web.py`'s explicit
   `RouteResult` boundary) is: Baseline's own code is the mediator and
   decision-maker for anything consequential, never a generic OS service
   trusted by default. A full portal daemon is one more opaque trust
   boundary between the app and the OS that Baseline doesn't control or
   audit as directly as its own small brokers.

So Milestone 2's four "first-supported capabilities" are implemented as
small, separately testable Python modules under `baseline/lib/gui_brokers/`,
each with an explicit, narrow interface - matching decision record 29's
"minimal access-broker boundary, not a generic framework" philosophy:

- **Notification** - `notify(app_id: str, summary: str, body: str) -> bool`.
  MVP implementation: durably logs the request (matches this project's
  `network.py` `EVENT_LOG` JSONL pattern) and returns success; no visual
  notification UI yet (no notification daemon exists in this minimal cage
  session) - explicitly a stub at "minimal, testable level," not a finished
  feature.
- **Clipboard** - `read_clipboard() -> str`, `write_clipboard(text: str) -> None`.
  Wraps `wl-copy`/`wl-paste` (lightweight, Wayland-native CLI tools, no
  portal or D-Bus needed) through the same `Runner`-injectable boundary
  `repair.py` established.
- **File-picker** - `list_exchange_files() -> list[str]`,
  `pick_exchange_file(name: str) -> Path | None`. Scoped to one
  Baseline-controlled "exchange" directory rather than a real portal-backed
  native file-chooser dialog (which would need a GTK/portal backend this
  milestone deliberately isn't adopting) - a pragmatic MVP simplification,
  flagged as such, not a claim that arbitrary filesystem browsing is solved.
- **Download/export** - not a bespoke broker at all: Chromium's own managed
  policy sets `DownloadDirectory` to that same Baseline-controlled exchange
  directory and disables the download-location prompt
  (`PromptForDownloadLocation: false`), so every download already lands
  somewhere Baseline mediates access to, reusing the browser's own policy
  mechanism instead of duplicating it.

## Browser launch under a generated policy

A small pure function, `browser_policy.generate(*, allowed_urls: list[str],
download_directory: str) -> dict`, produces the managed-policy JSON
Chromium reads from `/etc/chromium/policies/managed/baseline.json`:
`URLAllowlist` (scope the kiosk to only the intended app + what it needs),
`DownloadDirectory` / `PromptForDownloadLocation: false` (routes to the
export broker's directory), and a small set of privacy/safety defaults
(`BrowserSignin: 0`, `SyncDisabled: true`, `PasswordManagerEnabled: false`,
`DefaultBrowserSettingEnabled: false`). Pure and unit-testable - no
subprocess, no real file I/O in the function itself; the caller writes the
returned dict as JSON.

## Local routing for future app-sandbox work

Out of scope to *build* in this milestone (only one app - Chromium - exists
today), but the anticipated shape, so B3's code doesn't paint itself into a
corner: `cage`'s own model is one compositor session per window/app, not a
multi-app desktop. So "routing" between future apps means Baseline starts
and stops separate `cage` sessions (one per app) on the *same* dedicated GUI
VT, never overlapping - consistent with a kiosk device showing one thing at
a time, and with the "Baseline-managed start/stop/restart" exit criterion
below. `gui_session.py`'s lifecycle functions are written generically enough
(session name + launch command, not hardcoded to Chromium) that a future
second app reuses them unchanged.

## VT/lifecycle interaction with Baseline's tty1 ownership

Same proven pattern as Track A3's kiosk, on its own dedicated VT (not `tty1`,
not `tty2`'s Proxmox-return path, and not `tty3` if Track A3's own kiosk
service is present on the same machine) - `TTYPath`/`Conflicts=getty@ttyN.service`
ownership, gated by an explicit readiness check before start (mirroring
`kiosk_gate.py`, though B3's gate is simpler: "is the session supposed to be
running" rather than firstboot's `already_completed()`).

The PRD's explicit requirement - "failure to launch the GUI must return the
operator to Baseline's tty interface" - is proven directly in B3, not just
argued: kill the compositor process, confirm Baseline's own tty console
(whatever stands in for it in the disposable proof) is still reachable on
its own VT, unaffected.

## What B3 will build, concretely

- `baseline/lib/gui_session.py` - `Runner`-injectable session lifecycle:
  `start(runner, session) -> SessionHandle`, `stop(runner, handle) -> bool`,
  `restart(runner, handle) -> SessionHandle`, `is_running(runner, handle) -> bool`.
- `baseline/lib/browser_policy.py` - `generate(...)` as described above.
- `baseline/lib/gui_brokers/notification.py`, `clipboard.py`, `file_picker.py`
  - each `Runner`-injectable, each independently unit-tested with fakes, no
  real cage/chromium/wl-copy needed for the test suite.
- One disposable QEMU proof (not the real Track A hardware - Track B's own
  safety boundary: disposable images only, no persistence attached) driving
  all of the above for real: session starts, browser launches under the
  generated policy, the compositor is killed and tty fallback is confirmed
  reachable, then the image is deleted per this project's established
  retention discipline.
