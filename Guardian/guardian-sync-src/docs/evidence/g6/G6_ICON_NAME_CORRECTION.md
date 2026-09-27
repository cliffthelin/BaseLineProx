# G6 Evidence Correction — icon-name precision (fallback glyph vs. intended icon)

**Status: CORRECTION / CROSS-REFERENCE, not a re-run of settled candidate
conclusions.** This document does not overturn any PASS/FAIL
determination already recorded for candidate 1, candidate 2, or `ksni`.
It corrects an evidentiary-precision gap the independent audit found: the
original spike documents' "icon appears: PASS" screenshots show a
*fallback* glyph, not the *intended* `"emblem-default"` icon, and none of
them disclosed this distinction.

## What the independent audit found

`"emblem-default"`, hardcoded in all three original G6 candidate
prototypes, does not exist as an icon in any Adwaita build tested in this
gate -- confirmed independently in three separate VMs across this
project's full G6 history:

```text
find /usr/share/icons/Adwaita /usr/share/icons/hicolor -iname '*emblem-default*'
```
returns nothing, every time, regardless of package set breadth.

Pixel-level inspection (by the independent audit, and reconfirmed here)
showed:

- On GNOME, the original `G6_GNOME_KSNI_SPIKE_EVIDENCE.md` and
  `G6_AYATANA_GTK3_SPIKE_EVIDENCE.md` "icon-visible-pass" screenshots
  show a generic ellipsis-like ("...") glyph occupying the position a
  real icon would -- confirmed, by direct contrast against a true
  no-candidate baseline screenshot from the same VM session, to be
  genuinely attributable to the candidate (it is absent when no
  candidate is running) and not GNOME's own system menu icon
  coincidentally rendered at the same position.
- On Xfce, the original `G6_AYATANA_GTK3_SPIKE_EVIDENCE.md` screenshot
  shows a generic green-checkmark-in-circle glyph, likewise confirmed
  attributable to the candidate via baseline contrast.
- In the narrower-package VM used for `G6_P0_IND_003_RECONNECT_EVIDENCE.md`,
  the same missing icon name rendered with **zero visible content at
  all** -- a fully invisible, zero-width button -- which is what
  originally surfaced this whole finding (see that document's "read
  first" section).

The underlying defect is the same in every case: `St.Icon`/GTK icon-name
lookup fails silently (no exception, no error, no log line) when the
name does not resolve, and the *fallback rendering behavior differs by
icon theme/package-set completeness* -- sometimes a generic placeholder
glyph, sometimes nothing at all.

## What this does and does not change

**Does not change:** every "icon appears: PASS" determination already
recorded remains PASS. In every case, a real, attributable, interactive
UI element genuinely appeared (confirmed via true-baseline contrast, not
assumed), and in every case a real click on it opened a real,
candidate-specific menu with a real, log-confirmed handler response.
Candidate 2's FAIL determination is entirely unaffected -- it rests on a
directly thrown exception and an independent plugin debug-log error, not
on any icon-rendering ambiguity.

**Does change:** the precision of what "icon appears" evidenced. It
evidenced "a real, attributable, interactive indicator surface was
present," not "the intended icon asset rendered correctly." These are
different claims, and the original documents did not distinguish them.

## Corrections applied

The following original evidence documents are corrected by
cross-reference, per the closure brief's explicit instruction not to
rewrite prior observations:

- `G6_GNOME_KSNI_SPIKE_EVIDENCE.md` -- add a note under "Run 2" that the
  icon shown in `icon-visible-pass.png` is a generic fallback glyph
  (`"emblem-default"` does not resolve), not the intended icon; the
  underlying registration/click/menu evidence is unaffected. Cross-refers
  to this document.
- `G6_AYATANA_GTK3_SPIKE_EVIDENCE.md` -- same correction, for both the
  GNOME and Xfce `icon-visible-pass` screenshots.
- `G6_XFCE_KSNI_SPIKE_EVIDENCE.md` -- same correction, noting the fallback
  glyph shown for the Xfce icon-appears result.

## Icon names used in closure evidence gathered after this correction

To avoid repeating this ambiguity, all closure evidence gathered after
this correction (menu resolution, reconnect, logout/login, daemon-
unavailable) uses icon names directly verified present before use, via:

```text
find /usr/share/icons/{Adwaita,hicolor,Humanity} -iname '<name>.*'
```

run on the same VM used for that evidence, with non-symbolic (regular
color) variants confirmed present, not just symbolic ones:

```text
computer            -- 6 non-symbolic matches (healthy state)
dialog-warning       -- 7 non-symbolic matches (manually-simulated degraded state)
dialog-error         -- 7 non-symbolic matches (real detected daemon-unavailable state)
application-exit     -- 5 non-symbolic matches (Exit menu item icon, unchanged from original)
```

`tests/vm/g6-candidate-ksni/src/main.rs`'s own module doc comment records
this same information and the reasoning for each choice (distinct icons
for manually-simulated vs. really-detected degraded states, so a viewer
cannot confuse the two).
