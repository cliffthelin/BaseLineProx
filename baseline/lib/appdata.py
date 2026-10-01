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

import naming

KIND_PACKAGE = "apt package"
KIND_LXC = "lxc guest"
KIND_VM = "vm guest"
KIND_CONTAINER = "container"
KIND_FLATPAK = "flatpak"
KIND_APPIMAGE = "appimage"
KIND_SNAP = "snap"
KIND_NIX = "nix"

# Statuses, matching docs/layers/README.md's legend.
MVP_COMPLETED = "MVP completed"
IN_PROGRESS = "In progress"
ON_ROADMAP = "On roadmap"
IN_DISCOVERY = "In discovery"


@dataclass(frozen=True)
class Medium:
    """One medium's contract (direct instruction, 2026-09-30): "The medium
    will be an immediate method of use and rules and possible helpers
    available." Each medium stands alone - something wanted in two media
    is two separate applications with two identifiers.

    The governing rule across all of them: **never duplicate a sandbox
    that already exists.** Where a medium confines its apps already
    (Flatpak, Snap, OCI), Baseline adds AppData placement and leaves the
    medium's isolation alone; two permission models that can disagree is
    worse than one. Where it confines nothing (deb, AppImage), Baseline
    supplies the gap.

    `helpers` name real code, as "module" or "module.attribute"; a test
    resolves every one, so a contract can never cite something that does
    not exist. An empty tuple means no helper exists yet - stated, not
    implied."""
    letter: str                  # naming.MEDIA key
    kind: str
    name: str
    method_of_use: str           # how a person actually runs something in this medium
    rules: tuple                 # what Baseline enforces for it
    helpers: tuple               # real code that installs/applies it
    status: str
    brings_own_sandbox: bool
    isolation_mechanism: str
    requires: tuple
    baseline_must_supply: tuple
    data_root_template: str = ""  # per-app data convention; {app} substituted
    notes: str = ""

    def data_root(self, app_id: str) -> str:
        return self.data_root_template.format(app=app_id)

    # Back-compatible name used by the page and older tests.
    @property
    def format_id(self) -> str:
        return self.kind


MEDIA: dict = {m.kind: m for m in (
    Medium(
        "D", KIND_PACKAGE, "deb package",
        method_of_use="apt-get install on the host; run directly",
        rules=("installed files are the immutable lower layer and never written by Baseline",
               "every per-person data path is overlaid onto the app's own AppData tree",
               "a path with no per-person data gets no overlay, and says so"),
        helpers=("firstboot_statemachine", "config_apply.apply_cpu_microcode"),
        status=IN_PROGRESS,
        brings_own_sandbox=False,
        isolation_mechanism="none - a .deb installs system-wide and writes wherever it likes",
        requires=("apt",),
        baseline_must_supply=("data isolation", "access control", "registry"),
        notes="Installs are real (firstboot, provision.sh); the AppData overlays are planned, not applied.",
    ),
    Medium(
        "C", KIND_CONTAINER, "OCI container image",
        method_of_use="a Quadlet .container unit in the app's own rootless systemd instance",
        rules=("pulled by digest only - a tag is refused (UnpinnedImage)",
               "runs rootless as the app's own uid",
               "only its own AppData directories are bound in",
               "Baseline-rendered configuration is bound read-only",
               "admin/control ports are never published"),
        helpers=("appdata.container_spec", "quadlet.generate_unit", "quadlet.write_and_start"),
        status=IN_PROGRESS,
        brings_own_sandbox=True,
        isolation_mechanism="rootless podman: user + mount + network namespaces; the image's own non-root user",
        requires=("podman",),
        baseline_must_supply=("AppData bind placement", "pin by digest"),
        notes=("Data paths exist only inside the container's mount namespace, so a container gets "
               "bind mounts from its AppData home rather than host overlays. Two containers may "
               "each use /data without conflict for the same reason. The unit is generated for "
               "real; it has not been started (no podman on the build host)."),
    ),
    Medium(
        "L", KIND_LXC, "LXC guest",
        method_of_use="a Proxmox pct container created from a sha256-pinned helper script",
        rules=("created only from the curated, sha256-verified script catalog",
               "its rootfs is its own per-VMID path, never the shared Proxmox store",
               "its data disk lives on AppData so a rebuilt guest reattaches it"),
        helpers=("vm_scripts.run_script", "pct_provision"),
        status=IN_PROGRESS,
        brings_own_sandbox=True,
        isolation_mechanism="Linux namespaces + AppArmor via Proxmox pct",
        requires=("proxmox-ve",),
        baseline_must_supply=("AppData placement of the guest's disk",),
        notes="Scripts are real-executed in QEMU (decision record 97); AppData placement is planned.",
    ),
    Medium(
        "V", KIND_VM, "VM guest",
        method_of_use="a Proxmox qm virtual machine created from a sha256-pinned helper script",
        rules=("created only from the curated, sha256-verified script catalog",
               "its disk images are its own per-VMID path, never the shared Proxmox store",
               "its data disk lives on AppData so a rebuilt guest reattaches it"),
        helpers=("vm_scripts.run_script", "vm_provision"),
        status=IN_PROGRESS,
        brings_own_sandbox=True,
        isolation_mechanism="hardware virtualisation (KVM) via Proxmox qm",
        requires=("proxmox-ve",),
        baseline_must_supply=("AppData placement of the guest's disk",),
        notes="Scripts are real-executed in QEMU (decision record 97); AppData placement is planned.",
    ),
    Medium(
        "F", KIND_FLATPAK, "Flatpak",
        method_of_use="flatpak install <app-id>; flatpak run <app-id>",
        rules=("its ~/.var/app/<app-id> data root is overlaid onto AppData",
               "Flatpak's own sandbox is left in place, never duplicated"),
        helpers=(),
        status=ON_ROADMAP,
        brings_own_sandbox=True,
        isolation_mechanism="bubblewrap sandbox + per-app permissions, data already per-app under ~/.var/app/<app-id>",
        requires=("flatpak", "xdg-desktop-portal"),
        baseline_must_supply=("AppData placement only",),
        data_root_template="~/.var/app/{app}",
        notes=("Closest existing system to this model: OSTree is the immutable-store half, "
               "~/.var/app/<id> the per-app-data half. Open conflict: Flatpak's permissions depend on "
               "xdg-desktop-portal, which milestone-2-gui-plan.md declined on trust-model grounds "
               "(Baseline's own code mediates, not a generic OS service). Adopting Flatpak reopens "
               "that decision."),
    ),
    Medium(
        "A", KIND_APPIMAGE, "AppImage",
        method_of_use="download one executable file and run it; there is no install step",
        rules=("Baseline assigns the identity - a filename is not stable across versions",
               "Baseline supplies the sandbox (bubblewrap)",
               "data paths are declared per app, since there is no convention to derive them from"),
        helpers=(),
        status=ON_ROADMAP,
        brings_own_sandbox=False,
        isolation_mechanism="none - a single executable file, no install step, no manifest, no confinement",
        requires=("fuse",),
        baseline_must_supply=("sandbox", "app identity", "data isolation", "access control", "registry"),
        data_root_template="~/.config/{app}",
        notes="The medium where this model carries the most weight: it brings nothing of its own.",
    ),
    Medium(
        "S", KIND_SNAP, "Snap",
        method_of_use="snap install <name>; run through snapd",
        rules=("the overlay targets ~/snap/<name>/current so it survives a revision bump",
               "snapd's AppArmor confinement is left in place, never duplicated"),
        helpers=(),
        status=ON_ROADMAP,
        brings_own_sandbox=True,
        isolation_mechanism="AppArmor + seccomp confinement, data per-app under ~/snap/<name>/<revision>",
        requires=("snapd",),
        baseline_must_supply=("AppData placement only",),
        data_root_template="~/snap/{app}/current",
        notes=("snapd is an extra always-running daemon on a Debian/Proxmox substrate, and `current` "
               "is a symlink repointed on every refresh."),
    ),
    Medium(
        "N", KIND_NIX, "Nix",
        method_of_use="nix profile install / nix run",
        rules=(),
        helpers=(),
        status=IN_DISCOVERY,
        brings_own_sandbox=False,
        isolation_mechanism="none by itself - the /nix/store is immutable, but running programs are not confined",
        requires=("nix",),
        baseline_must_supply=("data isolation", "access control", "registry"),
        notes=("The immutable store is exactly the lower-layer half of this model, which is why it is "
               "listed. Whether Baseline adopts Nix as a medium is undecided."),
    ),
)}

# Older name kept for the page and tests that iterate "formats".
FORMATS = MEDIA


def format_for(kind: str) -> Medium | None:
    return MEDIA.get(kind)


def medium_for(kind: str) -> Medium:
    if kind not in MEDIA:
        raise ValueError(f"no medium for kind {kind!r}")
    return MEDIA[kind]


def confinement_gap(kind: str) -> tuple:
    """What Baseline itself must provide for this medium, given what the
    medium already does."""
    m = MEDIA.get(kind)
    return m.baseline_must_supply if m else ("unknown medium",)


def supported_formats() -> list:
    order = (KIND_PACKAGE, KIND_CONTAINER, KIND_LXC, KIND_VM, KIND_FLATPAK, KIND_SNAP,
             KIND_APPIMAGE, KIND_NIX)
    return [MEDIA[k] for k in order]


# Container-internal paths per image, from each image's own published
# config (read from the registry, not assumed). (container_path, read_only)
CONTAINER_BINDS: dict = {
    # Hummingbird caddy: XDG_DATA_HOME=/data (certificates, ACME state),
    # XDG_CONFIG_HOME=/config (autosaved config), and the Caddyfile its
    # Cmd reads. The Caddyfile is Baseline-rendered input, so the
    # container gets it read-only - caddy must not be able to rewrite
    # its own routing.
    "caddy": (("/data", False), ("/config", False), ("/etc/caddy", True)),
}

# Ports per image. Never includes an image's admin/control port: caddy
# exposes its admin API on 2019, and publishing it would let anything
# that can reach the host reconfigure the gateway.
CONTAINER_PUBLISH: dict = {
    "caddy": ("8080:8080", "8443:8443"),
}
CONTAINER_NEVER_PUBLISH: dict = {
    "caddy": (2019,),
}


@dataclass(frozen=True)
class ContainerBind:
    """One AppData directory bound into a container at a path the image
    already uses. Host side always lives under the app's own home."""
    host: str
    container: str
    read_only: bool = False

    def volume_arg(self) -> str:
        return f"{self.host}:{self.container}{':ro' if self.read_only else ''}"


# Persistent-data targets per application, by catalog id. A path here is a
# real location that application writes to and that must therefore be
# redirected onto AppData. An app absent from this map, or mapped to an
# empty tuple, genuinely has no per-person data (a library, a one-shot
# CLI) - recorded explicitly rather than guessed, so "no overlay" is a
# stated finding and never an oversight.
DATA_TARGETS: dict = {
    # --- deb packages ------------------------------------------------
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
    # A guest's persistent data is its OWN disk, never the shared Proxmox
    # storage directory. Targeting `/var/lib/vz/private` directly was a
    # real bug caught by `target_conflicts`: four LXC guests would each
    # have overlay-mounted the same path and silently shared it. Proxmox
    # lays guests out per-VMID; VMID is assigned at creation, so the
    # catalog id stands in here until the real VMID substitutes.
    "debian-lxc": ("/var/lib/vz/private/debian-lxc",),
    "docker-lxc": ("/var/lib/vz/private/docker-lxc",),
    "homeassistant-lxc": ("/var/lib/vz/private/homeassistant-lxc",),
    "pihole-lxc": ("/var/lib/vz/private/pihole-lxc",),
    "debian-vm": ("/var/lib/vz/images/debian-vm",),
    "haos-vm": ("/var/lib/vz/images/haos-vm",),
}


@dataclass(frozen=True)
class AppSpec:
    app_id: str                      # catalog id: provenance, and the default alias - never the identifier
    name: str
    kind: str
    source: str                      # the original installer it came from
    data_targets: tuple = ()         # real paths holding persistent data
    notes: str = ""
    image_ref: str = ""              # containers only: registry@digest, never a tag

    @property
    def medium(self) -> Medium:
        return medium_for(self.kind)

    @property
    def has_persistent_data(self) -> bool:
        return bool(self.data_targets) or bool(CONTAINER_BINDS.get(self.app_id))


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
    baseline_id: str                # naming identifier, e.g. A_C_00001
    id_allocated: bool              # False = a preview; the identifier is not reserved yet
    home: str                       # the app's own AppData tree, keyed by identifier
    registry_db: str                # its own registry, not a shared one
    owner_user: str                 # its own uid/gid, derived from the identifier
    owner_group: str
    mode: str                       # 0700 - no cross-app access
    alias: naming.AliasLink | None = None
    overlays: list = field(default_factory=list)
    binds: list = field(default_factory=list)   # containers: AppData -> container path

    @property
    def isolated(self) -> bool:
        """Every requirement the instruction named, verifiable per app."""
        return (self.home.startswith(APPDATA_PREFIX_MARKER)
                and self.home.endswith("/" + self.baseline_id)
                and self.registry_db.startswith(self.home + "/")
                and self.mode == "0700"
                and all(o.upperdir.startswith(self.home + "/") for o in self.overlays)
                and all(b.host.startswith(self.home + "/") for b in self.binds))


APPDATA_PREFIX_MARKER = "/mnt/APPDATA_"
APPDATA_MODE = "0700"
APP_CLUSTER = "A"


def appdata_label(persona: str) -> str:
    return f"APPDATA_{persona.upper()}"


def appdata_lv_name(persona: str) -> str:
    return f"baseline_appdata_{persona.lower()}"


def appdata_root(persona: str) -> str:
    """Per-persona, following the phone model: app data belongs to a
    person, so it lives under that person's own AppData volume."""
    return f"/mnt/{appdata_label(persona)}"


def app_home(persona: str, baseline_id: str) -> str:
    """Keyed by the constant identifier, never by a name - names are only
    aliases under by-name/, and a mount must never resolve through one."""
    return naming.canonical_path(appdata_root(persona), baseline_id)


def registry_path(persona: str, baseline_id: str) -> str:
    """Each application's own registry - a separate database inside its
    own AppData tree, never a row in a shared one."""
    return f"{app_home(persona, baseline_id)}/registry.db"


def _escape_target(target: str) -> str:
    """A filesystem-safe single directory name for one overlay target,
    so each target gets its own upper/work pair without nesting."""
    return target.replace("~", "HOME").strip("/").replace("/", "-") or "root"


def _skip_substrate_and_drivers(entry) -> bool:
    """Drivers are excluded by the instruction; the Proxmox source ISO is
    the substrate itself, not an application running on it."""
    import installer_cache as ic
    return entry.kind in (ic.KIND_FIRMWARE, ic.KIND_ISO)


def _guest_kind(entry_id: str) -> str:
    import vm_scripts
    info = vm_scripts.SCRIPT_MANIFEST.get(entry_id)
    return KIND_VM if info is not None and info.kind == "vm" else KIND_LXC


def installable_apps() -> list:
    """Everything installable that is not a driver, derived from
    installer_cache's catalog so the two cannot drift."""
    import installer_cache as ic
    apps = []
    for entry in ic.catalog():
        if _skip_substrate_and_drivers(entry):
            continue
        if entry.kind == ic.KIND_PACKAGE:
            kind = KIND_PACKAGE
        elif entry.kind == ic.KIND_SCRIPT:
            kind = _guest_kind(entry.entry_id)
        elif entry.kind == ic.KIND_IMAGE:
            kind = KIND_CONTAINER
        else:
            raise ValueError(f"catalog entry {entry.entry_id!r} has unmapped kind {entry.kind!r}")
        apps.append(AppSpec(
            app_id=entry.entry_id, name=entry.name, kind=kind, source=entry.origin,
            data_targets=tuple(DATA_TARGETS.get(entry.entry_id, ())), notes=entry.notes,
            image_ref=entry.pinned_ref if entry.kind == ic.KIND_IMAGE else "",
        ))
    return apps


def id_requests(apps=None) -> list:
    """(cluster, medium, subject) for every app - what naming allocates."""
    return [(APP_CLUSTER, app.medium.letter, app.app_id) for app in (apps or installable_apps())]


def effective_targets(app: AppSpec) -> tuple:
    """The real paths to overlay for one app. A medium with its own
    per-app data convention supplies its root, and that root is what gets
    overlaid - Baseline follows the medium's layout rather than imposing a
    second one beside it."""
    m = MEDIA.get(app.kind)
    if m is not None and m.data_root_template:
        return (m.data_root(app.app_id),)
    return app.data_targets


def plan_for(persona: str, app: AppSpec, assignment: naming.Assignment) -> AppPlan:
    """The full isolation plan for one app: its own data tree, registry
    and owner - all keyed by its identifier - plus overlays or binds.
    Every path is checked to be canonical (never through an alias)."""
    parsed = naming.parse_id(assignment.value)
    if parsed.cluster != APP_CLUSTER or parsed.medium != app.medium.letter:
        raise naming.NamingError(f"{assignment.value} does not match {app.app_id} "
                                 f"(cluster {APP_CLUSTER}, medium {app.medium.letter})")
    home = naming.assert_canonical(app_home(persona, assignment.value))
    owner = parsed.owner_name
    alias = naming.alias_link(appdata_root(persona), app.app_id, assignment.value)
    common = dict(app=app, baseline_id=assignment.value, id_allocated=assignment.allocated,
                  home=home, registry_db=f"{home}/registry.db", owner_user=owner,
                  owner_group=owner, mode=APPDATA_MODE, alias=alias)

    if app.kind == KIND_CONTAINER:
        binds = [ContainerBind(host=naming.assert_canonical(f"{home}/binds/{_escape_target(p)}"),
                               container=p, read_only=ro)
                 for p, ro in CONTAINER_BINDS.get(app.app_id, ())]
        return AppPlan(**common, binds=binds)

    overlays = [
        OverlayMount(
            target=target, lowerdir=target,
            upperdir=naming.assert_canonical(f"{home}/upper/{_escape_target(target)}"),
            workdir=naming.assert_canonical(f"{home}/work/{_escape_target(target)}"),
        )
        for target in effective_targets(app)
    ]
    return AppPlan(**common, overlays=overlays)


def plan_all(persona: str, assignments: dict | None = None) -> list:
    """Every app's plan. Without `assignments`, identifiers come from
    naming.preview: read-only, never creating the registry, with
    not-yet-allocated ones marked as such."""
    apps = installable_apps()
    if assignments is None:
        assignments = naming.preview(id_requests(apps))
    return [plan_for(persona, app, assignments[app.app_id]) for app in apps]


class UnpinnedImage(ValueError):
    """Raised rather than falling back to a tag: a tag is a moving
    pointer, and a self-replicating build that pulls one cannot say
    which bytes it shipped."""


def container_spec(plan: AppPlan):
    """The real quadlet.ContainerSpec for a container plan - rootless,
    running as the app's own identity, pulled by digest, with only its
    own AppData bound in and never its admin port published."""
    import quadlet
    if plan.app.kind != KIND_CONTAINER:
        raise ValueError(f"{plan.app.app_id} is not a container")
    if "@sha256:" not in plan.app.image_ref:
        raise UnpinnedImage(f"{plan.app.app_id} has no digest-pinned image reference")
    return quadlet.ContainerSpec(
        name=f"baseline-{plan.baseline_id.lower()}",
        image=plan.app.image_ref,
        description=f"{plan.baseline_id} ({plan.app.app_id}) - AppData {plan.home}",
        volumes=[b.volume_arg() for b in plan.binds],
        publish=list(CONTAINER_PUBLISH.get(plan.app.app_id, ())),
        rootless=True,
        user=plan.owner_user,
    )


def published_ports(plan: AppPlan) -> set:
    """Host-side and container-side port numbers this plan publishes."""
    ports = set()
    for mapping in CONTAINER_PUBLISH.get(plan.app.app_id, ()):
        for part in mapping.split(":"):
            ports.add(int(part))
    return ports


def required_directories(plan: AppPlan) -> list:
    """Every directory that must exist, mode 0700, owned by the app,
    before any overlay or bind in this plan can mount."""
    dirs = [plan.home, f"{plan.home}/upper", f"{plan.home}/work"]
    for overlay in plan.overlays:
        dirs.extend([overlay.upperdir, overlay.workdir])
    for bind in plan.binds:
        dirs.append(bind.host)
    return dirs


def target_conflicts(plans: list) -> list:
    """Any overlay target claimed by more than one application. Two
    overlays cannot both mount at one path - the second hides the first
    and the apps share exactly the data this module keeps apart."""
    seen: dict = {}
    for plan in plans:
        for overlay in plan.overlays:
            seen.setdefault(overlay.target, []).append(plan.app.app_id)
    return [(target, owners) for target, owners in sorted(seen.items()) if len(owners) > 1]


def cross_app_leaks(plans: list) -> list:
    """Any case where one app's writable layer falls inside another's
    tree. Must always be empty - the isolation guarantee as a check."""
    leaks = []
    for plan in plans:
        for other in plans:
            if other.app.app_id == plan.app.app_id:
                continue
            for overlay in plan.overlays:
                if overlay.upperdir.startswith(other.home + "/"):
                    leaks.append((plan.app.app_id, other.app.app_id, overlay.upperdir))
            for bind in plan.binds:
                if bind.host.startswith(other.home + "/"):
                    leaks.append((plan.app.app_id, other.app.app_id, bind.host))
    return leaks


def identifier_collisions(plans: list) -> list:
    """Two applications given the same identifier. Must always be empty."""
    seen: dict = {}
    for plan in plans:
        seen.setdefault(plan.baseline_id, []).append(plan.app.app_id)
    return [(i, owners) for i, owners in sorted(seen.items()) if len(owners) > 1]
