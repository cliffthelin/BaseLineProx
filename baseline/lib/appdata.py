"""Per-application AppData: isolation, registry, access and data.

Direct instruction, 2026-09-30: "Application data is personal owned
application data and does not go anywhere other than an AppData
persistence volume or container. Each application should have its own
isolation and registry and access and data." Scope: "Anything
installable that is not a driver." Mechanism: "It is a change inspired
by Phone operating systems and Nixos and Qubes and you need to do
overlays for each that puts its data here."

The three inspirations, and what each contributes here:

- **Phone OS** - every app gets its own data directory under the
  *user*, not a shared one (`/data/user/<uid>/<pkg>`). AppData is
  therefore per-persona, not one machine-wide store: app data is
  personal-owned, so it is owned by a person.
- **NixOS** - the installed base is immutable and never written to.
  Nothing here mutates a package's own installed files; the base is
  always the overlay's read-only `lowerdir`.
- **Qubes** - isolation is the default, not an opt-in. An app can only
  reach its own tree; there is no shared writable surface to fall back
  to, which is why no "default" or "common" AppData path exists in
  this module.

**What an overlay actually does here.** A real app writes to real
system paths (`/var/lib/pihole`, `~/.config/chromium`). Rather than
rewriting every app to point somewhere else - which is fragile and
only works for software we control - each such path is overlay-mounted
in place: `lowerdir` is the original immutable content, `upperdir` is
on the persona's AppData volume, and every write the app makes lands
in the upper layer. The app sees an ordinary filesystem; the data is
personal-owned and on AppData, with no cooperation from the app.

**Drivers are excluded by the instruction.** Firmware and microcode
are not applications and have no personal data - they are properties of
the hardware, not of a person. `installable_apps()` filters them out,
and a test asserts it.

This module is **planning only**. It computes real mount
specifications, paths and identities; it never mounts, chowns or
writes anything. Applying a plan is privileged and destructive and
belongs behind the same explicit, operator-authorized path Drive
Administration uses - not a side effect of rendering a page.
"""
from __future__ import annotations

from dataclasses import dataclass, field

KIND_PACKAGE = "apt package"
KIND_GUEST = "vm/lxc guest"
KIND_CONTAINER = "container"

# Persistent-data targets per application, by app id. A path here is a
# real location that application writes to and that must therefore be
# redirected onto AppData. An app absent from this map, or mapped to an
# empty tuple, genuinely has no persistent per-person data (a library, a
# one-shot CLI) - that is recorded explicitly rather than guessed at, so
# "no overlay" is a stated finding and never an oversight.
DATA_TARGETS: dict = {
    # --- apt packages ------------------------------------------------
    "chromium": ("~/.config/chromium", "~/.cache/chromium"),
    "podman": ("~/.local/share/containers",),
    "smartmontools": ("/var/lib/smartmontools",),
    "lm-sensors": (),        # reads hardware; config is substrate-level (/etc/sensors.d)
    "nvme-cli": (),          # pure query tool
    "iperf3": (),            # pure measurement tool
    "ethtool": (),           # pure NIC query/apply tool
    "inxi": (),              # pure reporting tool
    "python3-rich": (),      # library
    "python3-textual": (),   # library
    "tmux": ("~/.tmux",),
    "gnupg": ("~/.gnupg",),
    "cage": (),              # compositor; holds no per-person state itself
    "nodejs": ("~/.npm",),
    # --- VM / LXC guests ---------------------------------------------
    # A guest's persistent data is its OWN disk, never the shared
    # Proxmox storage directory. Targeting `/var/lib/vz/private`
    # directly was a real bug caught by `target_conflicts`: four LXC
    # guests would each have overlay-mounted the same path, so the last
    # mount would win and the other three would silently share - the
    # exact opposite of the isolation this module exists to provide.
    # Proxmox lays guests out per-VMID (`/var/lib/vz/private/<VMID>`,
    # `/var/lib/vz/images/<VMID>`); VMID is assigned at creation, so the
    # app id stands in here and the real VMID substitutes when the guest
    # is actually created.
    "debian-lxc": ("/var/lib/vz/private/debian-lxc",),
    "docker-lxc": ("/var/lib/vz/private/docker-lxc",),
    "homeassistant-lxc": ("/var/lib/vz/private/homeassistant-lxc",),
    "pihole-lxc": ("/var/lib/vz/private/pihole-lxc",),
    "debian-vm": ("/var/lib/vz/images/debian-vm",),
    "haos-vm": ("/var/lib/vz/images/haos-vm",),
}


@dataclass(frozen=True)
class AppSpec:
    app_id: str
    name: str
    kind: str
    source: str                      # the original installer it came from
    data_targets: tuple = ()         # real paths holding persistent data
    notes: str = ""

    @property
    def has_persistent_data(self) -> bool:
        return bool(self.data_targets)


@dataclass(frozen=True)
class OverlayMount:
    """One real overlay: the app's own writable layer over an immutable
    base, mounted back at the path the app already uses."""
    target: str          # where the app reads/writes (the merged mount point)
    lowerdir: str        # immutable installed base - never written to
    upperdir: str        # the app's personal writable layer, on AppData
    workdir: str         # overlayfs scratch; must share a filesystem with upperdir

    def mount_argv(self) -> list:
        opts = f"lowerdir={self.lowerdir},upperdir={self.upperdir},workdir={self.workdir}"
        return ["mount", "-t", "overlay", "overlay", "-o", opts, self.target]


@dataclass
class AppPlan:
    app: AppSpec
    home: str                       # the app's own AppData tree
    registry_db: str                # its own registry, not a shared one
    owner_user: str                 # its own uid/gid
    owner_group: str
    mode: str                       # 0700 - no cross-app access
    overlays: list = field(default_factory=list)

    @property
    def isolated(self) -> bool:
        """Every requirement the instruction named, verifiable per app."""
        return (self.home.startswith(APPDATA_PREFIX_MARKER)
                and self.registry_db.startswith(self.home)
                and self.mode == "0700"
                and all(o.upperdir.startswith(self.home) for o in self.overlays))


APPDATA_PREFIX_MARKER = "/mnt/APPDATA_"
APPDATA_MODE = "0700"


def appdata_label(persona: str) -> str:
    return f"APPDATA_{persona.upper()}"


def appdata_lv_name(persona: str) -> str:
    return f"baseline_appdata_{persona.lower()}"


def appdata_root(persona: str) -> str:
    """Per-persona, following the phone model: app data belongs to a
    person, so it lives under that person's own AppData volume."""
    return f"/mnt/{appdata_label(persona)}"


def app_home(persona: str, app_id: str) -> str:
    return f"{appdata_root(persona)}/{app_id}"


def app_identity(app_id: str) -> tuple:
    """Its own access: a dedicated unprivileged uid/gid per app, so
    filesystem permissions alone prevent one app reading another's
    data even outside a container."""
    safe = app_id.replace("_", "-")
    return (f"baseline-app-{safe}", f"baseline-app-{safe}")


def _escape_target(target: str) -> str:
    """A filesystem-safe single directory name for one overlay target,
    so each target gets its own upper/work pair without nesting."""
    return target.replace("~", "HOME").strip("/").replace("/", "-") or "root"


def _skip_substrate_and_drivers(entry) -> bool:
    """Drivers are excluded by the instruction; the Proxmox source ISO
    is the substrate itself, not an application running on it."""
    import installer_cache as ic
    if entry.kind == ic.KIND_FIRMWARE:
        return True
    if entry.kind == ic.KIND_ISO:
        return True
    return False


def installable_apps() -> list:
    """Everything installable that is not a driver, derived from
    installer_cache's catalog so the two cannot drift."""
    import installer_cache as ic
    kind_map = {ic.KIND_PACKAGE: KIND_PACKAGE, ic.KIND_SCRIPT: KIND_GUEST}
    apps = []
    for entry in ic.catalog():
        if _skip_substrate_and_drivers(entry):
            continue
        apps.append(AppSpec(
            app_id=entry.entry_id,
            name=entry.name,
            kind=kind_map.get(entry.kind, KIND_CONTAINER),
            source=entry.origin,
            data_targets=tuple(DATA_TARGETS.get(entry.entry_id, ())),
            notes=entry.notes,
        ))
    return apps


def plan_for(persona: str, app: AppSpec) -> AppPlan:
    """The full isolation plan for one app: its own data tree, its own
    registry, its own owner, and one overlay per real data target."""
    home = app_home(persona, app.app_id)
    user, group = app_identity(app.app_id)
    overlays = [
        OverlayMount(
            target=target,
            lowerdir=target,
            upperdir=f"{home}/upper/{_escape_target(target)}",
            workdir=f"{home}/work/{_escape_target(target)}",
        )
        for target in app.data_targets
    ]
    return AppPlan(app=app, home=home, registry_db=f"{home}/registry.db",
                   owner_user=user, owner_group=group, mode=APPDATA_MODE,
                   overlays=overlays)


def plan_all(persona: str) -> list:
    return [plan_for(persona, app) for app in installable_apps()]


def registry_path(persona: str, app_id: str) -> str:
    """Each application's own registry - a separate database inside its
    own AppData tree, never a row in a shared one."""
    return f"{app_home(persona, app_id)}/registry.db"


def required_directories(plan: AppPlan) -> list:
    """Every directory that must exist, mode 0700, owned by the app,
    before any overlay in this plan can mount."""
    dirs = [plan.home, f"{plan.home}/upper", f"{plan.home}/work"]
    for overlay in plan.overlays:
        dirs.extend([overlay.upperdir, overlay.workdir])
    return dirs


def target_conflicts(plans: list) -> list:
    """Any overlay target claimed by more than one application.

    A real defect this caught: every LXC guest originally targeted
    `/var/lib/vz/private`. Two overlays cannot both mount at one path -
    the second hides the first, and the apps end up sharing exactly the
    data this module exists to keep apart. Upperdir separation alone
    does not prevent it, so it is checked on the target as well."""
    seen: dict = {}
    for plan in plans:
        for overlay in plan.overlays:
            seen.setdefault(overlay.target, []).append(plan.app.app_id)
    return [(target, owners) for target, owners in sorted(seen.items()) if len(owners) > 1]


def cross_app_leaks(plans: list) -> list:
    """Any case where one app's writable layer falls inside another's
    tree. Must always be empty - this is the isolation guarantee stated
    as a check rather than a comment."""
    leaks = []
    for plan in plans:
        for other in plans:
            if other.app.app_id == plan.app.app_id:
                continue
            for overlay in plan.overlays:
                if overlay.upperdir.startswith(other.home + "/"):
                    leaks.append((plan.app.app_id, other.app.app_id, overlay.upperdir))
    return leaks
