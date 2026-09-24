"""Storage and boot facts: mounts, block devices, bootloader config,
kernel command line, EFI presence. Kernel cmdline is redacted per
identity-bearing argument (root=UUID=..., resume=..., and similar) since
those values can be as identifying as a disk serial."""
from .status_notes import notes as _notes


def collect_storage(runner):
    mounts = runner.run(["findmnt", "-D"])
    blocks = runner.run(["lsblk", "-f"])
    return {
        "mounts": mounts.stdout if mounts.ok else None,
        "block_devices": blocks.stdout if blocks.ok else None,
        "_collection_notes": _notes((mounts, "findmnt -D"), (blocks, "lsblk -f")),
    }


_IDENTITY_ARG_MARKERS = ("uuid", "root=", "resume=", "partuuid")


def _redact_cmdline(cmdline, redactor):
    out = []
    for arg in cmdline.split():
        if "=" in arg and any(marker in arg.lower() for marker in _IDENTITY_ARG_MARKERS):
            key, value = arg.split("=", 1)
            out.append(f"{key}={redactor.tokenize(value, 'cmdline-arg')}")
        else:
            out.append(arg)
    return " ".join(out)


def collect_boot(runner, redactor):
    grub = runner.read_text("/etc/default/grub")
    cmdline = runner.read_text("/proc/cmdline")
    boot_tool_path = runner.which("proxmox-boot-tool")
    boot_tool = runner.run(["proxmox-boot-tool", "status"]) if boot_tool_path else None
    efi_present = runner.path_exists("/sys/firmware/efi")
    efibootmgr_path = runner.which("efibootmgr")
    efi_entries = runner.run(["efibootmgr"]) if efibootmgr_path else None
    entry_count = None
    if efi_entries and efi_entries.ok:
        entry_count = sum(1 for line in efi_entries.stdout.splitlines() if line.startswith("Boot"))
    collection_notes = _notes((grub, "read /etc/default/grub"), (cmdline, "read /proc/cmdline"))
    if boot_tool is not None:
        collection_notes += _notes((boot_tool, "proxmox-boot-tool status"))
    elif not boot_tool_path:
        collection_notes.append({"command": "proxmox-boot-tool status", "status": "unavailable", "reason": "proxmox-boot-tool not on PATH"})
    if efi_entries is not None:
        collection_notes += _notes((efi_entries, "efibootmgr"))
    elif not efibootmgr_path:
        collection_notes.append({"command": "efibootmgr", "status": "unavailable", "reason": "efibootmgr not on PATH"})
    return {
        "grub_default": grub.stdout if grub.ok else None,
        "kernel_cmdline": _redact_cmdline(cmdline.stdout, redactor) if cmdline.ok else None,
        "proxmox_boot_tool_status": boot_tool.stdout if boot_tool and boot_tool.ok else None,
        "efi_present": efi_present,
        "efi_boot_entry_count": entry_count,
        "_collection_notes": collection_notes,
    }
