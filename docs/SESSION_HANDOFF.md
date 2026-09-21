# Session handoff - moving to the "Baseline" Claude Project

Written from the CLI session that did tonight's bare-metal bring-up work,
for you to paste into / cross-check against the new Claude Project. I
have no access to that Project (it's a claude.ai web feature, not
reachable from this CLI session), so I can't verify what did or didn't
transfer - this is the definitive account from this side, not a diff.

## READ THIS FIRST - active drive incident, partially resolved

The laptop's boot drive (a 28.7GB USB stick, `/dev/sdb`, holding the
`pve-root` LVM volume that everything runs from) had a real failure
event. **A verified, uncorrupted partial backup now exists** (see
below), but the drive itself is still degraded/read-only and the root
cause (wedged software state vs. genuine media failure) is still
unresolved. Whoever continues this needs to pick up here before
anything else.

**Timeline (2026-09-20):**
- `16:01:40` - kernel logs `usb 2-1.2: USB disconnect, device number 4`
  for the boot drive.
- `16:01:47` - ext4's journal aborts, several `Buffer I/O error`s, the
  root filesystem (`dm-1`, i.e. `pve-root`) remounts itself read-only
  (`errors=remount-ro` kernel safety trigger). Confirmed still
  read-only as of the end of this session (`touch` fails with
  "Read-only file system").
- User confirmed the physical USB connection is seated ("It's plugged
  in"). No new USB disconnect events logged since. Reads continue to
  mostly fail regardless (see below) with a stable connection, which
  points more toward (b) below.
- A full filesystem walk (via Python, since `/usr/bin/tar` itself fails
  to execute with a consistent I/O error) hit **15,372-15,373
  I/O-error failures out of ~18,338 files attempted (~84% failure
  rate)**, spread across essentially every directory - not localized.
  **`/usr/bin/rsync` also failed to execute** with the same I/O error
  pattern as `tar`, while `python3`, `cat`, and plain file reads kept
  working reliably throughout. Two different, unrelated system
  binaries failing to load points toward (b) **genuine, fairly
  extensive media failure** on the drive, more than (a) a simple
  software wedge - not conclusively proven, but the working theory.
- **Three backup attempts; the third succeeded and is verified valid**:
  1. Python `tarfile.add()` directly - corrupted (writes the tar header
     before copying content, so a read failing partway through a file
     desynced everything after it in the stream).
  2. Buffered each file fully into memory first (should have avoided
     the above) - **still corrupted**, breaking after 4247 entries.
     Root cause never fully identified - suspected but unconfirmed:
     `tarfile.gettarinfo()`'s PAX-header prep may use stat-time size
     before the manual `ti.size` override, desyncing PAX-format
     entries specifically. Do not reuse `tarfile` for this host without
     understanding that first.
  3. **Abandoned `tarfile`/any archive-format library entirely.**
     Custom minimal framing (tag byte + length-prefixed path + length-
     prefixed data, written by a remote Python process, parsed by a
     local Python process into individual real files on local disk -
     see `remote_backup3.py`/`local_receive.py` if still present in
     that session's scratchpad, otherwise trivial to rewrite from this
     description) - **worked cleanly**: 2966 files, 417MB, local
     receiver's count matched the remote sender's count exactly, zero
     errors. Repackaged locally (purely local tar of local files, no
     remote I/O involved, so no corruption risk) into
     `partial-verified-20260920-1817.tar.gz`, 139.8MB,
     sha256 `6a03a37ad58e8c6744d6e3e3e069446583044891b0d158c2081e19e82e454d09`
     - **both `gzip -t` and `tar tzf` pass cleanly on this one.**
     Contains the real, critical files: all of `/opt/baseline`
     (including `bin/baseline` itself, which `tar` couldn't read),
     `/etc/systemd/system/baseline.service`, `/etc/baseline/*`
     (**including the live `harness.env` OAuth token and
     `interface_aliases.json`**), and `/etc/ssh/ssh_host_*_key`
     (**including the private host keys**).
  **This archive contains live secrets - never commit it to the public
  BaseLineProx repo or any public location.** It was sent directly to
  the user via chat only. The two earlier *corrupted* archives were
  deleted (not useful, superseded by the working one); the raw failure
  logs from attempt 2 were kept and also sent to the user directly.
- **Still not captured**: ~13,605-15,372 files (the ~84% that fail to
  read at all right now) - most of the base OS, kernel, `/boot`, most
  of `/usr`. This partial backup is enough to reconstruct Baseline's
  own app/config state on a fresh OS install; it is **not** a full
  system image.
- **No reboot of the laptop has been attempted.** That's the standard
  next step to try clearing an ext4 journal-abort wedge, but it's a
  real risk on the *only* boot drive and needs explicit authorization -
  don't assume it. Given the working theory has shifted toward genuine
  media failure (see above), a reboot may not actually help and the
  drive should likely be treated as failing hardware regardless of
  whether it happens to come back read-write after one.

**Recommended next steps for whoever picks this up:**
1. Treat this drive as failing hardware needing replacement soon, not
   just a one-off glitch to route around - two independent binaries
   failing to load with a stable physical connection is a strong
   signal. The NVMe-migration conversation from earlier this session
   (see "Not done" below) is no longer hypothetical.
2. If more data recovery is wanted before replacing the drive, reuse
   the working custom-framing approach (attempt 3 above), not
   `tarfile`/`tar`/`rsync` - all three failed or were unreliable on
   this specific degraded filesystem for reasons not fully understood.
3. Get explicit authorization before rebooting the laptop.
4. Handle `partial-verified-20260920-1817.tar.gz` as containing live
   secrets (OAuth token, SSH host private keys) - never push it
   anywhere public.

## Do this first (before anything else works)

**SSH access to the laptop needs to be re-established.** The key I've
been using all session lives at a path inside *this* session's own
temporary scratchpad directory - it does not exist anywhere the new
Project can reach. Either:
- Generate a fresh keypair from the new Project's environment and add
  the public half to the laptop's `~/.ssh/authorized_keys` (you'll need
  physical/console access to do that one-time step - `baseline`'s
  Console tab or the Proxmox round-trip feature, see below, both give
  you a shell), or
- Copy an existing private key into wherever the new Project's
  persistent storage is, if one is being kept.

**The laptop's IP changes.** It's DHCP (`vmbr0`), currently
`10.0.0.133`, but it has changed at least twice already this session
(`.181` -> `.133`). Don't hardcode it as fact anywhere; check via
`ip -4 -o addr show` over the console, or your router's DHCP lease
list, before assuming SSH will connect.

## What exists and where

- **Live device**: a Dell Latitude 5290 laptop, Proxmox VE 9.2 bare
  metal, `baseline.service` owns tty1 (real console, not a VM/QEMU
  session at this point in the project).
- **Source of truth repo**: `/run/media/cane/CACHE/baseline_repo` on
  this machine (persistent storage - `/tmp` and drive-letter paths were
  both burned early in the project as unreliable across reboots, see
  `docs/BAREMETAL_BRINGUP_NOTES.md`).
- **GitHub**: <https://github.com/cliffthelin/BaseLineProx> (public),
  `main` branch, tip commit `07eda93` as of this handoff - confirmed to
  contain everything described below.
- **Deployed app path on the laptop**: `/opt/baseline/{bin,lib}`,
  `/etc/baseline/` (preferences/aliases/auth token), `/etc/systemd/
  system/baseline.service`.
- A **second, pre-existing private repo**, `cliffthelin/baseline`,
  unexpectedly received a push from this session too (a `git remote`
  mix-up - see the git-workflow note below). I don't know its history.
  Worth checking directly whether it should be archived/deleted or is
  intentional and predates this session.

## Standing rules the user has set (do not relitigate these)

- **Never use theme/variable colors** ($primary, $surface, etc.) in any
  Textual CSS - always explicit hardcoded hex. This has caused multiple
  illegible-UI bugs already; the bare `TERM=linux` framebuffer console
  renders theme colors unreliably.
- **No fake/decorative buttons or forms.** Every control must do a real
  thing. Where real functionality isn't ready yet (e.g. hardware
  Configuration tab), say so honestly in the UI rather than faking it.
- **Implement real functionality now, don't defer it** - the user has
  explicitly rejected "wait and build it properly later" multiple
  times.
- **No non-ASCII characters anywhere in rendered output** - found and
  removed the app's only Unicode use (arrow glyphs) after multiple
  `TERM=linux` rendering bugs this session; the bare console's font
  can't be assumed to have arbitrary glyphs.
- **Never open a new file descriptor to `/dev/tty1` (or any tty device
  node) from within the running Baseline process.** An earlier attempt
  to do this (for a character-grid query) correlated with real console
  font-table corruption ("garble") that persisted across service
  restarts. Use `os.get_terminal_size()` (reads the process's own
  already-open stdout) instead - see `docs/changelog/hardware/001.md`
  and `boot/001.md` for the full story.
- **Verify before declaring anything done.** The established pattern
  all session: edit locally -> deploy to the laptop -> run a headless
  Textual pilot test (`app.run_test()`) reproducing the actual
  interaction -> restart the service -> confirm stability via
  `systemctl status` (immediate + after a few seconds, to catch crash-
  loops) -> ask the user to visually confirm on the physical screen,
  since no screenshot pipeline exists for this console.
- **Every deployed change gets a change-log entry.** See
  `docs/changelog/INDEX.md` - check it first, it points to category
  files (boot/hardware/network/ui/chat), each an append-only, rotating
  block. Use `docs/changelog/TEMPLATE.md` for the entry format
  (Context/Considered/Requirement/Files changed/Verification/Pointer
  update/Docs update). This is a standing process now, not a one-off.

## What's actually done (verified live, not just written)

- Full vertical-slice PRD V0.1: boot to a Baseline prompt on tty1,
  deterministic hardware status (`inxi`-based), network bring-up
  (wired/Wi-Fi/USB-tether) with per-stage Lifeline diagnostics, a
  read-only Claude Code harness (zero tools, hardware/network JSON as
  its only context).
- A full Textual TUI (Hardware/Network/Chat/Console tabs) replacing the
  original plain Rich console output, with real keyboard navigation
  (Tab/Down/Shift+Tab, all independently verified working), explicit
  hardcoded colors throughout, and crash containment (Textual treats
  any unhandled exception as fatal to the whole app - confirmed in its
  own source - so render callbacks and event handlers are wrapped to
  log-and-continue instead).
- **Hardware tab**: shows every `inxi` fact (not a curated subset),
  grouped, each row opening a modal (Details/Description/
  Troubleshooting/Logs/Configuration - last four are honest
  placeholders).
- **Network tab**: correct Available-vs-Unreachable logic for wired vs.
  wireless links, IP + live traffic on the main row, and a
  `ConnectionModal` per interface with real bridged hardware identity
  (manufacturer/model/connection-type/driver, via `udevadm` - works for
  onboard and USB devices alike), a renameable, persisted alias, a real
  working Enable/Disable, Primary/Fallback as a genuine arrow-navigable
  toggle (not two momentary buttons), and its live position in the
  Lifeline chain when it's the active device.
- **Boot/console robustness**: fixed a `getty.target` systemd ordering
  cycle that could hang boot entirely; fixed `inxi` failing under the
  service's minimal environment; fixed console font-table corruption
  via an `ExecStartPre` `setfont` plus a standalone, re-runnable check
  (`tests/console_font_check.sh`, also wired into `provision.sh`).
- **A real Proxmox<->BaselineOS console round trip**: `(p)` inside
  Baseline switches tty1's physical console to tty2, which starts a
  genuine, unmodified login prompt (systemd-logind auto-starts the
  getty - no unit needed enabling by hand); a `baseline` shell function
  (installed system-wide via `/etc/profile.d/`) switches back to tty1
  without disturbing Baseline's already-running state. **Login stays
  required on the Proxmox side by explicit user decision** - not
  bypassed, don't add auto-login without asking again.
- This change-log system itself (`docs/changelog/`), backfilled with
  tonight's work.

## Not done - open items for the new Project

1. **Chat tab quality** - the biggest open item, discussed at length but
   **no code written yet**. Current state: `harness.ask()` is a single
   stateless `claude -p <prompt> --tools ""` call per message - no
   memory, no streaming, full hardware/network re-scan before every
   message. The agreed direction (confirmed against the real installed
   `claude --help`, flags genuinely exist):
   - `--session-id <uuid>` + `-c/--continue` for real multi-turn memory
   - `-p --output-format stream-json` for real incremental streaming
   - `--allowedTools`/`--disallowedTools` as a real, named, auditable
     access-scope control, exposed as a visible/toggleable header item
     rather than the current hardcoded empty string
   - Explicitly **rejected**: embedding the actual interactive `claude`
     CLI in a raw PTY widget (real effort, reintroduces a "how do I get
     keyboard focus back" problem the chosen approach avoids entirely
     since Baseline stays the only terminal renderer).
   - Also wanted: a condensed one-line header bar (`BaselineOS | tabs |
     access scope | memory | copy | datetime`) with the header/footer
     frozen (already true today via Textual's normal dock behavior,
     just needs the new content added), and a real clipboard "copy"
     action (OSC 52 escape sequence is the standard mechanism for a TUI
     to reach the *local* clipboard of whatever's attached - not yet
     verified as working over this specific console/SSH path).
   - See `docs/changelog/chat/001.md` for the full decision record.
2. **Screen-size-appropriate layout** - verified live that the console
   is already running best-case (i915 KMS, native 1366x768 panel,
   170x48 character grid - not a degraded fallback), but the header/
   toggle-bar design should still target an 80x24 floor for hardware
   where KMS isn't available. Not designed yet.
3. **Storage migration** - brand new ask, not started: a 512GB NVMe
   (tested at 1.2GB/s on the user's main machine) as a candidate
   replacement for the current persistent storage, pending a real speed
   test from the laptop's own USB-C port (Thunderbolt support assumed,
   not confirmed).
4. Older, still-open items from earlier in the project (carried
   forward, not reconfirmed this session):
   - Provider "configuration forms" deliberately still not built
     (credential handling stays out of Baseline's own hands by design -
     see `baseline/lib/harness.py`'s docstring for the reasoning).
   - Static-IP and LVM-reclaim manual fixes documented but not folded
     into `provision.sh`.
   - File-transfer/shared-folder capability for the phone-tether rescue
     channel (scoped as v0.2, not started).
   - Only the `claude` harness is implemented; OpenCode/Hermes/Pi/
     DeepSeek/GrokBot remain listed-but-honestly-marked-unimplemented in
     the Chat tab's harness selector.

## Where to look for more detail

- `docs/changelog/INDEX.md` - check first, points to everything else.
- `docs/BAREMETAL_BRINGUP_NOTES.md` - accumulated real-hardware gotchas
  (QEMU vs. bare-metal VT-switching, DHCP client quirks, USB tethering,
  the dhclient `-timeout` bug, etc.).
- `docs/adr/0001-bare-metal-network-bootstrap.md` - the two network
  route-selection bugs found early on, written up as an ADR.
- The original PRD context lives in this chat's history, not yet
  extracted into a repo doc - if the new Project needs it and doesn't
  have it, ask for it explicitly rather than assuming it's here.
