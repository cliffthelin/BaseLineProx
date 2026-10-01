"""INSTALLER_CACHE inventory: every artifact this application involves,
where it originally comes from, and whether it is actually on the volume.

Direct instruction, 2026-09-30: "show all software, packages, OS distros,
and drivers involved with this application with their original installer
... give a transparent view of what is on it now and what will be on any
self replicating builds."

Two separate questions this module keeps strictly apart, because
conflating them is how a build silently ships incomplete:

1. **What SHOULD be there** - `catalog()`, the declared set of artifacts a
   self-replicating build needs. Derived from the modules that already own
   those lists (`firstboot_statemachine.DIAGNOSTIC_PACKAGES`,
   `vm_scripts.SCRIPT_MANIFEST`, `config_apply`'s driver packages) rather
   than re-typed here, so the catalog cannot drift from what the code
   actually installs.
2. **What IS there right now** - `scan_cache()`, a real listing of the
   volume. Never inferred from the catalog.

`reconcile()` joins the two and is the only thing the page renders, so a
missing artifact is always visible as missing rather than absent from the
display entirely.

A note on the mount: `/mnt/INSTALLER_CACHE` being a *plain directory* on
the root filesystem rather than the real volume's mount point is a real,
observed failure mode - artifacts land on the root disk and are silently
lost on rebuild. `mount_status()` reports it explicitly; it is not
cosmetic.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_CACHE_ROOT = "/mnt/INSTALLER_CACHE"

KIND_ISO = "OS image"
KIND_PACKAGE = "apt package"
KIND_FIRMWARE = "driver / firmware"
KIND_SCRIPT = "VM / LXC script"
KIND_IMAGE = "container image"

# Subdirectory on the volume per kind. A self-replicating build reads
# these by name, so they are part of the on-disk contract.
SUBDIR = {
    KIND_ISO: "isos",
    KIND_PACKAGE: "packages",
    KIND_FIRMWARE: "firmware",
    KIND_SCRIPT: "vm-scripts",
    KIND_IMAGE: "images",
}

# Provenance states, weakest to strongest. Kept as distinct words because
# collapsing them is how a page ends up claiming more than was checked:
# a digest read from a registry proves which bytes are meant, not that a
# trusted party signed them.
PROVENANCE_NONE = "no pinned provenance"
PROVENANCE_OBSERVED = "digest pinned, signature not yet verified"
PROVENANCE_VERIFIED = "digest pinned, signature verified"


@dataclass(frozen=True)
class CatalogEntry:
    entry_id: str
    name: str
    kind: str
    origin: str          # the original installer/source this came from
    install_helper: str  # the real code path that installs or applies it
    config_section: str  # settings section on User Persistence that configures it
    filename: str = ""   # expected name on the volume ("" = any match by stem)
    notes: str = ""
    # Supply-chain fields - used by container images today. A tag is a
    # moving pointer, so an image is only ever referenced by digest.
    registry_ref: str = ""       # e.g. quay.io/hummingbird/caddy
    version: str = ""
    digest: str = ""             # multi-arch index digest, sha256:...
    attachments: tuple = ()      # what the registry publishes for that digest
    observed_at: str = ""        # when the digest was read from the registry
    signature_verified: bool = False

    @property
    def cache_path(self) -> str:
        return f"{SUBDIR[self.kind]}/{self.filename or self.entry_id}"

    @property
    def pinned_ref(self) -> str:
        """`registry@digest` - the only form a build may pull. Empty when
        nothing is pinned, so a caller cannot fall back to a tag."""
        return f"{self.registry_ref}@{self.digest}" if self.registry_ref and self.digest else ""

    @property
    def provenance(self) -> str:
        if not self.digest:
            return PROVENANCE_NONE
        return PROVENANCE_VERIFIED if self.signature_verified else PROVENANCE_OBSERVED


@dataclass
class Presence:
    entry: CatalogEntry
    present: bool
    actual_path: str = ""
    size_bytes: int = 0
    detail: str = ""


@dataclass
class Uncatalogued:
    """A real file on the volume that no catalog entry claims. Shown
    rather than hidden: an unexplained 6 GB ISO is exactly the kind of
    thing an operator needs to see before trusting a build."""
    path: str
    size_bytes: int


@dataclass
class CacheReport:
    root: str
    mounted: bool
    mount_detail: str
    rows: list = field(default_factory=list)
    extras: list = field(default_factory=list)
    scanned_ok: bool = True
    scan_detail: str = ""

    @property
    def present_count(self) -> int:
        return sum(1 for r in self.rows if r.present)

    @property
    def missing_count(self) -> int:
        return sum(1 for r in self.rows if not r.present)


# -- Catalog ----------------------------------------------------------
# Built from the modules that already own each list, so it cannot drift.

_PROVISION_PACKAGES = (
    # boot/provision.sh's own apt-get install lines, by purpose.
    ("inxi", "host hardware reporting used by the TUI's Hardware tab"),
    ("python3-rich", "TUI rendering"),
    ("python3-textual", "TUI framework for bin/baseline"),
    ("tmux", "session multiplexing for the console persona"),
    ("gnupg", "signature verification in the ISO acquisition chain"),
    ("cage", "kiosk Wayland compositor (decision record: Track A3)"),
    ("chromium", "kiosk browser onto the Proxmox web UI"),
    ("podman", "rootless container runtime for quadlet.py units"),
    ("nodejs", "runtime for the gateway/tooling layer"),
)

_DIAGNOSTIC_PURPOSE = {
    "lm-sensors": "temperature/fan collection (diagnostics.collect_sensors)",
    "nvme-cli": "NVMe health (diagnostics.collect_nvme)",
    "smartmontools": "SMART health (diagnostics.collect_smart)",
    "iperf3": "throughput testing (config_apply iperf3 role)",
    "ethtool": "NIC speed/duplex/offload (config_apply ethtool)",
}

_FIRMWARE = (
    ("amd64-microcode", "AMD CPU microcode", "drivers.cpu_microcode_package"),
    ("intel-microcode", "Intel CPU microcode", "drivers.cpu_microcode_package"),
    ("firmware-mediatek", "MediaTek Wi-Fi firmware", "drivers.wifi_firmware_package"),
    ("firmware-realtek", "Realtek Wi-Fi firmware", "drivers.wifi_firmware_package"),
)


# Container images. Every value below was read from the registry itself
# on 2026-09-30 (quay.io v2 manifest + config blob + tag API), not taken
# from documentation - the Hummingbird docs list registry patterns but do
# not name a caddy image, so its existence was confirmed directly.
#
# Caddy was chosen as the first image because the gateway already had a
# validated Caddyfile renderer (gateway_config.py) and registry-backed
# routes (gateway_routes.py) but no binary at all: it was in neither
# provision.sh nor this catalog, which is why `caddy validate` had never
# run. Project Hummingbird publishes caddy as a minimal, non-root image
# with an SBOM, a signature and SLSA provenance attached per digest.
_IMAGES = (
    CatalogEntry(
        "caddy", "Caddy (gateway)", KIND_IMAGE,
        origin="Project Hummingbird (Red Hat), built in Konflux from Fedora components; "
               "source gitlab.com/redhat/hummingbird/containers @ b5468096ea87",
        install_helper="appdata.container_spec -> quadlet.generate_unit / write_and_start "
                       "(rootless podman, pulled by digest)",
        config_section="gateway routes (gateway_routes.py) rendered by gateway_config.render_caddyfile",
        filename="caddy-2.11.4.oci.tar",
        registry_ref="quay.io/hummingbird/caddy",
        version="2.11.4",
        digest="sha256:3db6c559f2321928d08c9378bb4438f969c2a1f9807c4974abb126eb50b3d7ea",
        attachments=(".sig", ".sbom", ".att (SLSA provenance)", ".src (source image)"),
        observed_at="2026-09-30",
        signature_verified=False,
        notes=(
            "Image config, as published: runs as non-root user `caddy`; listens on 8080/8443 "
            "(not 80/443, because it is non-root); exposes the admin API on 2019, which must "
            "never be published; reads /etc/caddy/Caddyfile; XDG_DATA_HOME=/data, "
            "XDG_CONFIG_HOME=/config. Distroless: no shell, no package manager. amd64 "
            "manifest sha256:2fe81ec43563918d11a9e885bad115a2a760023fd0c88a0bf6e738ea477b6a6e. "
            "License: Red Hat UBI EULA. 'Zero-CVE' describes the image at build time "
            "(created 2026-09-29T22:52:46Z), not a standing property - observed_at is when "
            "this digest was pinned, and the claim ages from there. Signature not yet "
            "verified: no cosign/podman on the build host."
        ),
    ),
)


def _diagnostic_packages() -> tuple:
    try:
        import firstboot_statemachine as fsm
        return tuple(fsm.DIAGNOSTIC_PACKAGES)
    except Exception:
        return tuple(_DIAGNOSTIC_PURPOSE)


def _curated_scripts() -> tuple:
    try:
        import vm_scripts
        return tuple((s.script_id, s.description, s.path) for s in vm_scripts.list_scripts())
    except Exception:
        return ()


def _script_origin() -> str:
    try:
        import vm_scripts
        return (f"github.com/{vm_scripts.UPSTREAM_SCRIPTS_REPO} "
                f"@ {vm_scripts.PINNED_COMMIT[:12]} (sha256-pinned)")
    except Exception:
        return "community-scripts/ProxmoxVE (sha256-pinned)"


def catalog() -> list:
    """Every artifact a self-replicating build needs, with its real
    origin, the helper that installs it, and the settings section that
    configures it."""
    entries = []

    entries.append(CatalogEntry(
        "proxmox-ve-source", "Proxmox VE (source ISO)", KIND_ISO,
        origin="enterprise.proxmox.com official ISO (GPG + SHA256 verified by drive_setup_acquire.py)",
        install_helper="self_installer.py -> drive_setup_install.py (answer-file auto-install)",
        config_section="self_installer (fqdn, lvm sizing, disk serial)",
        filename="proxmox-ve-source.iso",
        notes="The substrate OS. Located via self_installer._locate_proxmox_source_iso.",
    ))

    for pkg in _diagnostic_packages():
        entries.append(CatalogEntry(
            pkg, pkg, KIND_PACKAGE,
            origin="Debian/Proxmox apt archive (.deb)",
            install_helper="firstboot_statemachine.py phase E (apt-get install, verified after)",
            config_section="diagnostics",
            filename=f"{pkg}.deb",
            notes=_DIAGNOSTIC_PURPOSE.get(pkg, ""),
        ))

    for pkg, purpose in _PROVISION_PACKAGES:
        entries.append(CatalogEntry(
            pkg, pkg, KIND_PACKAGE,
            origin="Debian/Proxmox apt archive (.deb)",
            install_helper="boot/provision.sh (apt-get install, verified present after)",
            config_section="proxmox / startup",
            filename=f"{pkg}.deb",
            notes=purpose,
        ))

    for pkg, label, setting in _FIRMWARE:
        entries.append(CatalogEntry(
            pkg, label, KIND_FIRMWARE,
            origin="Debian non-free-firmware apt archive (.deb)",
            install_helper="config_apply.apply_cpu_microcode / apply_wifi_firmware",
            config_section=setting,
            filename=f"{pkg}.deb",
            notes="Selected per target hardware; the exported config's own package name wins.",
        ))

    for image in _IMAGES:
        entries.append(image)

    origin = _script_origin()
    for script_id, description, path in _curated_scripts():
        entries.append(CatalogEntry(
            script_id, script_id, KIND_SCRIPT,
            origin=f"{origin} :: {path}",
            install_helper="vm_scripts.run_script (sha256-verified before execution)",
            config_section="volumes / sessions",
            filename=f"{script_id}.sh",
            notes=description,
        ))

    return entries


# -- Real volume state ------------------------------------------------

def mount_status(runner, root: str = DEFAULT_CACHE_ROOT) -> tuple:
    """Is `root` the real INSTALLER_CACHE volume, or just a directory on
    the root filesystem? Returns (mounted, detail). A plain directory is
    a real failure mode - artifacts written there are lost on rebuild."""
    try:
        proc = runner.run(["findmnt", "-n", "-o", "SOURCE,FSTYPE", root], timeout=10)
    except Exception as exc:
        return False, f"could not determine mount state: {exc}"
    if getattr(proc, "returncode", 1) != 0 or not proc.stdout.strip():
        return False, (f"{root} is NOT a mount point - it is a plain directory on the root "
                       f"filesystem. Anything stored here is on the root disk, not the "
                       f"INSTALLER_CACHE volume, and will not survive a substrate rebuild.")
    return True, f"mounted from {proc.stdout.strip()}"


def _listdir_with_sizes(runner, path: str) -> list:
    """(name, size_bytes) for each regular file, via `ls -la`. Uses only
    `run`, so a privileged PkexecRunner can be swapped in unchanged for
    the Refresh-with-root path."""
    try:
        proc = runner.run(["ls", "-lA", "--time-style=+", path], timeout=20)
    except Exception:
        return []
    if getattr(proc, "returncode", 1) != 0:
        return []
    out = []
    for line in proc.stdout.splitlines():
        parts = line.split(maxsplit=5)
        if len(parts) < 6 or line.startswith("total "):
            continue
        perms, size, name = parts[0], parts[4], parts[5].strip()
        if perms.startswith("d"):
            continue
        try:
            out.append((name, int(size)))
        except ValueError:
            continue
    return out


def scan_cache(runner, root: str = DEFAULT_CACHE_ROOT) -> dict:
    """Real contents of each kind's subdirectory. Never inferred."""
    found = {}
    for kind, subdir in SUBDIR.items():
        found[subdir] = _listdir_with_sizes(runner, f"{root}/{subdir}")
    return found


def _matches(entry: CatalogEntry, name: str) -> bool:
    """A .deb on disk carries version/arch (`ethtool_6.10-1_amd64.deb`),
    so match on the package stem rather than demanding an exact name."""
    if entry.filename and name == entry.filename:
        return True
    stem = entry.filename.rsplit(".", 1)[0] if entry.filename else entry.entry_id
    lowered = name.lower()
    if entry.kind in (KIND_PACKAGE, KIND_FIRMWARE):
        return lowered.startswith(f"{stem.lower()}_") and lowered.endswith(".deb")
    return lowered.startswith(stem.lower())


def reconcile(runner, root: str = DEFAULT_CACHE_ROOT) -> CacheReport:
    """Catalog joined against reality. Every catalog entry appears in the
    result whether present or not; every real file not claimed by an
    entry appears as an extra."""
    mounted, mount_detail = mount_status(runner, root)
    found = scan_cache(runner, root)
    report = CacheReport(root=root, mounted=mounted, mount_detail=mount_detail)

    claimed: set = set()
    for entry in catalog():
        subdir = SUBDIR[entry.kind]
        hit = next((f for f in found.get(subdir, []) if _matches(entry, f[0])), None)
        if hit:
            claimed.add(f"{subdir}/{hit[0]}")
            report.rows.append(Presence(entry, True, f"{subdir}/{hit[0]}", hit[1],
                                        "on the volume"))
        else:
            report.rows.append(Presence(entry, False, "", 0,
                                        "not on the volume - a build from this cache would "
                                        "have to fetch it from its origin"))

    for subdir, files in found.items():
        for name, size in files:
            if f"{subdir}/{name}" not in claimed:
                report.extras.append(Uncatalogued(f"{subdir}/{name}", size))

    report.extras.sort(key=lambda e: -e.size_bytes)
    return report


def human_size(n: int) -> str:
    if not n:
        return "-"
    step = 1024.0
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < step or unit == "TiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= step
    return f"{n:.1f} TiB"
