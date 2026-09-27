# G6 Evidence Spike — Candidate 3 (`ksni`) on Xfce 4.20

**Status: CHECKPOINT, not a complete G6 candidate-comparison record.** This
document covers exactly one candidate (`ksni`/direct Rust SNI) against
exactly one target environment (Xfce 4.20), continuing directly from
`G6_GNOME_KSNI_SPIKE_EVIDENCE.md` (same candidate, GNOME 50). It does
**not** cover the other two required candidates or either P0-IND-003
reconnect scenario.

## Environment

```text
VM:              disposable qemu overlay, base image never modified
                 (same base image as the GNOME run, reused unmodified)
OS:               Ubuntu 26.04 LTS (Resolute Raccoon)
Desktop:          Xfce 4.20.4-1 (xfce4-session), lightdm 1.32.0-6ubuntu4
                  as display manager -- confirmed via `dpkg -l`
Setup script:     docs/evidence/g6/g6-xfce-vm-setup.sh (reproducible)
Capture method:   QEMU QMP `screendump` + `input-send-event` (same
                  technique as the GNOME run)
Run window:       2026-09-01T00:44Z (VM boot) -- 2026-09-01T01:02Z (teardown)
Teardown:         candidate process SIGTERM'd and confirmed exited (both
                  runs); panel plugin-ids array reverted to its original
                  10-plugin baseline (the added indicator plugin removed,
                  panel restarted to apply); overlay disk deleted; qemu
                  process terminated via QMP `quit` and confirmed gone.
```

## Candidate

Same prototype as the GNOME run: `tests/vm/g6-candidate-ksni/` (ksni
0.3.6), rebuilt from source inside this VM (not copied from the GNOME
VM's build -- each VM is independently disposable).

## Run 1 — stock Xfce 4.20 panel (default plugin layout)

A default `xfce4` install's panel already includes a legacy `systray`
plugin (Xfce's own "Notification Area," present at panel position 6 in
the default layout -- confirmed via `xfconf-query -c xfce4-panel -p
/plugins/plugin-6`) -- unlike GNOME, which ships with no tray/indicator
support at all by default.

**Real captured stdout/stderr:**

```text
[g6-evidence] G6 EVIDENCE-ONLY ksni prototype starting, pid=12927
[g6-evidence] tray.spawn() succeeded, StatusNotifierItem registered
```

Screenshot: `xfce420-ksni/candidate-ksni0.3.6_env-xfce420-stock-panel_2026-09-01T00-55-00Z_spawned-but-no-icon.png` --
`tray.spawn()` returns success (unlike GNOME's hard `ServiceUnknown`
error), but **no icon is visible anywhere in the panel**, confirmed by
direct visual comparison against the pre-candidate baseline screenshot
(byte-for-byte identical panel contents).

**Result: FAIL** for icon-appears, in a way distinct from the GNOME
failure mode. This is exactly the "process running but no visible icon"
adversarial case: the StatusNotifierItem D-Bus registration succeeds
(something on the session bus accepts the registration, most plausibly
the `indicator-application` service pulled in as a dependency of
`libayatana-appindicator3-1`), but Xfce's stock `systray` plugin
implements only the legacy XEmbed tray protocol and has no awareness of
StatusNotifierItem at all -- registering via D-Bus and being drawn by the
legacy XEmbed-only widget are two unrelated things.

## Run 2 — with `xfce4-indicator-plugin` added to the panel

```text
sudo apt-get install -y xfce4-indicator-plugin libayatana-appindicator3-1
xfconf-query -c xfce4-panel -p /plugins/plugin-11 -n -t string -s indicator
xfconf-query -c xfce4-panel -p /panels/panel-1/plugin-ids -n -a \
  -t int -s 1 ... -t int -s 11   # full array, appending 11
xfce4-panel -r
```

(Restarting the panel briefly triggered `light-locker` to lock the
session -- an artifact of this specific evidence-gathering environment,
not of the candidate under test; resolved by restarting `lightdm`, which
re-entered the already-configured autologin session cleanly. Documented
here for reproducibility, not as a candidate finding.)

**Real captured stdout/stderr:**

```text
[g6-evidence] G6 EVIDENCE-ONLY ksni prototype starting, pid=14485
[g6-evidence] tray.spawn() succeeded, StatusNotifierItem registered
```

Screenshot: `xfce420-ksni/candidate-ksni0.3.6_env-xfce420-indicator-plugin_2026-09-01T00-59-00Z_icon-visible-pass.png` --
**icon visibly present** in the top panel next to the "ubuntu" username
label.

**Provenance check (real scratch mutation, not just a single screenshot):**
the candidate process was killed (`pkill -TERM`) and a fresh screenshot
taken immediately after
(`candidate-none_..._icon-gone-after-kill-confirms-provenance.png`) --
the icon is confirmed gone. This positively attributes the icon to the
candidate process itself, not to an unrelated panel/system icon that
happened to be present at the same time.

**Result for icon-appears: PASS**, specifically *given* the
`xfce4-indicator-plugin` package is installed and added to the panel
layout (this package is not part of a default `xfce4` install; a stock
Ubuntu Xfce spin's actual default plugin set was not independently
verified this pass -- see "Not yet established" below).

> **Correction (added during G6 evidence closure, not a re-run of this
> spike): see `G6_ICON_NAME_CORRECTION.md`.** The `"emblem-default"` icon
> name used above does not exist in the tested Adwaita build; the glyph
> shown in `icon-visible-pass.png` (a green checkmark-in-circle) is a
> generic fallback icon, not the intended one -- confirmed by direct
> contrast against `candidate-none_..._icon-gone-after-kill-confirms-provenance.png`,
> which shows the same panel with that glyph genuinely absent. This does
> not change the PASS determination above: a real, attributable,
> interactive element genuinely appeared. Later G6 closure evidence uses
> icon names verified present before use.

### Menu-opens: UNRESOLVED, not established either way

Three real synthetic-click attempts (via QMP `input-send-event`, at the
icon's confirmed on-screen coordinates, with the mouse hover state
visually confirmed via the panel's own hover-highlight box in the
screenshot) did not produce a visible popup menu, and a
`dbus-monitor --session "interface='com.canonical.dbusmenu'"` capture
spanning one of the click attempts recorded no `dbusmenu` traffic at all
-- meaning the click never reached the point of even requesting the menu
layout from the candidate process.

This is being reported honestly as **unresolved**, not as a candidate
FAIL: it is not yet established whether this is (a) a genuine
interaction/compatibility gap between `ksni`'s DBusMenu implementation
and `xfce4-indicator-plugin` specifically, or (b) a limitation of this
evidence-gathering technique's synthetic-click targeting against this
specific plugin's click-handling widget (as distinct from GNOME's
AppIndicator extension, where the identical technique worked cleanly on
the first real attempt -- see the GNOME evidence document). Resolving
this would require either a real human-driven mouse interaction (e.g.
via a real VNC client) or deeper investigation of the plugin's actual
click-handling code -- both out of scope for this checkpoint pass.

**Screenshot evidence of the attempt:**
`xfce420-ksni/candidate-ksni0.3.6_..._menu-click-attempt-no-menu-observed.png`.

## What this run does and does not establish

Established, with real evidence:

- `ksni` does **not** produce a visible icon on a stock Xfce 4.20 panel
  (the default `systray`/XEmbed plugin does not understand SNI), even
  though the D-Bus registration itself succeeds -- a distinct failure
  mode from GNOME's (which fails at registration itself).
- With `xfce4-indicator-plugin` explicitly added to the panel, the icon
  does appear, and this was positively attributed to the candidate
  process via a real kill-and-reconfirm check.
- Xfce 4.20, like GNOME 50, requires an additional package/plugin beyond
  a bare desktop-environment install for this candidate to be visible at
  all -- reinforcing the GNOME run's finding that "dependency/mechanism
  considerations" are a real, non-trivial part of this candidate's actual
  compatibility story on both target desktops, not just GNOME.

Not yet established (explicitly out of scope for this checkpoint, or
genuinely unresolved):

- Whether `xfce4-indicator-plugin` (or an equivalent) ships by default on
  a real Xubuntu/Ubuntu-with-Xfce install, as opposed to the bare
  `apt-get install xfce4` set used here -- not independently verified.
- Menu-opens, menu-action-invokes-handler, and status/icon-update-
  propagates for Xfce specifically -- none demonstrated this pass (menu
  interaction unresolved as described above; the other two depend on
  first getting the menu open).
- "No X11 dependency" -- moot for Xfce 4.20, which is X11-based by
  design in this Ubuntu 26.04 packaging (unlike the GNOME 50/Wayland
  target) -- worth flagging explicitly for the eventual candidate
  comparison record, since the contract's own P0-IND-001 names
  "GNOME 50/Wayland" specifically while P0-IND-002 names only "Xfce 4.20
  Status Tray" with no Wayland/X11 qualifier.
- The other two required candidates, and both P0-IND-003 reconnect
  scenarios -- not tested.
- A final candidate selection or ADR-006 -- premature, same reasoning as
  the GNOME evidence document.

## Reproducibility

`docs/evidence/g6/g6-xfce-vm-setup.sh` reproduces the VM/Xfce/plugin
setup from a clean host, reusing the same base cloud image as the GNOME
setup script. The candidate prototype is the same
`tests/vm/g6-candidate-ksni/` used for the GNOME run.
