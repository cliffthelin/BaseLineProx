# DR151 — Hardware categories, drive navigation and package associations

Accepted 2026-10-04, direct instruction to connect Hardware drives to Drive
Administration, add sub-tabs and associate packages. Extends DR149; no storage
action permission or destructive gate changes.

Hardware now has Configuration, Drives, Network, Graphics, USB, Audio, System
and other, and Packages and firmware sub-tabs. Each category lists its devices
and driver controls. Tabs support keyboard navigation and linked category URLs.
Health/diagnostic results remain secondary and inventory is no longer duplicated.
A failed VM target listing is shown without blocking host hardware configuration.

Host drive rows link to Drive Administration using serial, never a persistent
kernel device path. Fresh eligible-drive discovery supplies the serial to the
card model. The page selects only a current matching drive. If a requested drive
is absent or excluded, it leaves every other drive unselected and reports why.
Existing destructive helpers still validate targets independently. Guest disks
link to VM disk configuration; they do not select physical host drives.

Hardware categories associate storage, network, system diagnostics and firmware
with existing Installer Cache catalog entries. The associated package table
reads actual installed version/status from dpkg-query, with failed observation
shown as unknown, not missing. Cache rows have stable anchors for these links.
Catalog purpose associations are not hardware compatibility recommendations.

Per-device driver controls also observe installed module binary ownership using
modinfo and an exact dpkg-query path match. Built-in drivers are labelled as such.
Unowned/generated modules have explicit unavailable ownership, never a guessed
package. An observed owning package absent from Installer Cache is labelled
not yet declared there. Acquiring/updating every such artifact is still the
existing Installer Cache checklist item; these changes do not fake installation
or source verification.

Verification: 320 focused Python checks passed, covering drafts, real local HTTP
routing, drive selection, hardware inventories, package/module contracts and
related pages. Real Chromium verified category switching, deep links, keyboard
navigation, package links and the matching drive radio selection against isolated
fixture inventory. Real host dpkg-query package observation was checked read-only.
No real module was loaded or package installed; no physical target was modified,
no native machine boot was verified, and fixture hardware is not physical proof.

Current docs/checklist were updated; DR149 remains append-only history. Wider
installer acquisition, VM device/passthrough and physical PC401 boot work remain
open under queue72/74/75/76/78.

Deployment: the desktop Baseline web application was reloaded with the new
modules, retaining its configured state directory. GET /login returned HTTP200.
Operator sessions reset on reload; log in again to use the updated pages.
