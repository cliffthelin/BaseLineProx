"""OS/platform-level facts: packages, APT, kernel/Proxmox/Debian
versions, firmware/drivers, systemd units, kernel-module/udev config,
runtimes. Grouped into one file (the design doc originally sketched one
file per category) since each of these is a handful of bounded
subprocess calls - nothing here is Proxmox-specific, see proxmox.py for
that.

Conffile-modified state is queried for every package in one batched
dpkg-query pass, never once per package (design doc correction #7).
Raw dmidecode output is parsed and discarded within collect_firmware_drivers()
- only the allowlisted summary fields ever leave this function (correction
#5: "never retained in normalized output").

Every collector here also returns "_collection_notes": a list of what
didn't come through and why (not installed, timed out, permission
denied, truncated) - never a silent None/[]/{} that looks the same as
"genuinely nothing found" (pre-run-safeguard requirement).
"""
from . import apt_sources
from .status_notes import notes as _notes

DMI_BIOS_ALLOWED = {"Vendor": "bios_vendor", "Version": "bios_version", "Release Date": "bios_release_date"}
DMI_SYSTEM_ALLOWED = {"Manufacturer": "system_manufacturer", "Product Name": "system_product"}


def collect_packages(runner):
    listing = runner.run(["dpkg-query", "-W", "-f=${Package}\t${Version}\t${Status}\n"])
    items = []
    if listing.ok:
        for line in listing.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                items.append({"name": parts[0], "version": parts[1], "status": parts[2]})

    holds_result = runner.run(["apt-mark", "showhold"])
    held = set(holds_result.stdout.split()) if holds_result.ok else set()
    for item in items:
        item["held"] = item["name"] in held

    # One batched pass for every package's Conffiles metadata, not one
    # dpkg-query invocation per package.
    conffiles_result = runner.run(["dpkg-query", "-W", "-f=${Package}\t${Conffiles}\n"])
    conffile_state = {}
    if conffiles_result.ok:
        for line in conffiles_result.stdout.splitlines():
            if "\t" not in line:
                continue
            pkg, rest = line.split("\t", 1)
            if rest.strip():
                conffile_state[pkg] = rest.strip()

    arch_result = runner.run(["dpkg", "--print-architecture"])
    foreign_result = runner.run(["dpkg", "--print-foreign-architectures"])
    return {
        "items": items,
        "architecture": arch_result.stdout.strip() if arch_result.ok else None,
        "foreign_architectures": foreign_result.stdout.split() if foreign_result.ok else [],
        "conffile_state_by_package": conffile_state,
        "_collection_notes": _notes(
            (listing, "dpkg-query -W (packages)"),
            (holds_result, "apt-mark showhold"),
            (conffiles_result, "dpkg-query -W (conffiles)"),
            (arch_result, "dpkg --print-architecture"),
            (foreign_result, "dpkg --print-foreign-architectures"),
        ),
    }


def collect_apt(runner):
    """Legacy `.list` AND Deb822 `.sources` repositories, both fully
    parsed - see apt_sources.py's module docstring for why reading only
    the legacy format is a real drift-hiding gap on a modern install,
    not a stylistic preference."""
    repos = apt_sources.collect(runner)
    policy = runner.run(["apt-cache", "policy"])
    return {
        "repositories": repos["entries"],
        "policy_available": policy.ok,
        "policy_summary": policy.stdout[:4000] if policy.ok else None,
        "_collection_notes": repos["_collection_notes"] + _notes((policy, "apt-cache policy")),
    }


def collect_platform_versions(runner):
    kernel = runner.run(["uname", "-a"])
    proxmox = runner.run(["pveversion", "-v"])
    debian = runner.read_text("/etc/debian_version")
    return {
        "kernel": kernel.stdout.strip() if kernel.ok else None,
        "proxmox": proxmox.stdout.strip() if proxmox.ok else None,
        "debian": debian.stdout.strip() if debian.ok else None,
        "_collection_notes": _notes(
            (kernel, "uname -a"),
            (proxmox, "pveversion -v"),
            (debian, "read /etc/debian_version"),
        ),
    }


def _parse_dmidecode(text, allowed):
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in allowed:
            out[allowed[key]] = value.strip()
    return out


def collect_firmware_drivers(runner):
    modules = runner.run(["lsmod"])
    pci = runner.run(["lspci", "-nnk"])
    bios = runner.run(["dmidecode", "-t", "bios"])
    system = runner.run(["dmidecode", "-t", "system"])

    bios_summary = {}
    if bios.ok:
        bios_summary.update(_parse_dmidecode(bios.stdout, DMI_BIOS_ALLOWED))
    if system.ok:
        bios_summary.update(_parse_dmidecode(system.stdout, DMI_SYSTEM_ALLOWED))
    # bios.stdout / system.stdout (the raw dmidecode text, which can carry
    # serials/UUIDs/asset tags) go out of scope here - only bios_summary,
    # built from an explicit key allowlist, is ever returned.

    return {
        "modules": modules.stdout.splitlines() if modules.ok else [],
        "pci_driver_bindings": pci.stdout if pci.ok else None,
        "bios_summary": bios_summary,
        "_collection_notes": _notes(
            (modules, "lsmod"),
            (pci, "lspci -nnk"),
            (bios, "dmidecode -t bios"),
            (system, "dmidecode -t system"),
        ),
    }


def collect_systemd_units(runner):
    enabled = runner.run(["systemctl", "list-unit-files", "--state=enabled"])
    delta = runner.run(["systemd-delta"])
    return {
        "enabled_units": enabled.stdout.splitlines() if enabled.ok else [],
        "systemd_delta_findings": delta.stdout if delta.ok else None,
        "_collection_notes": _notes(
            (enabled, "systemctl list-unit-files --state=enabled"),
            (delta, "systemd-delta"),
        ),
    }


def collect_kernel_udev(runner):
    modules_load_d = runner.listdir("/etc/modules-load.d")
    modprobe_d = runner.listdir("/etc/modprobe.d")
    udev_rules = runner.listdir("/etc/udev/rules.d")
    return {
        "modules_load_d": modules_load_d.stdout.splitlines() if modules_load_d.ok else [],
        "modprobe_d": modprobe_d.stdout.splitlines() if modprobe_d.ok else [],
        "udev_rules": udev_rules.stdout.splitlines() if udev_rules.ok else [],
        "_collection_notes": _notes(
            (modules_load_d, "listdir /etc/modules-load.d"),
            (modprobe_d, "listdir /etc/modprobe.d"),
            (udev_rules, "listdir /etc/udev/rules.d"),
        ),
    }


def collect_runtimes(runner):
    python_v = runner.run(["python3", "--version"])
    node_path = runner.which("node")
    node_v = runner.run(["node", "--version"]) if node_path else None
    collection_notes = _notes((python_v, "python3 --version"))
    if node_v is not None:
        collection_notes += _notes((node_v, "node --version"))
    elif not node_path:
        collection_notes.append({"command": "node --version", "status": "unavailable", "reason": "node not on PATH"})
    return {
        "python": python_v.stdout.strip() if python_v.ok else None,
        "node": node_v.stdout.strip() if node_v and node_v.ok else None,
        "_collection_notes": collection_notes,
    }
