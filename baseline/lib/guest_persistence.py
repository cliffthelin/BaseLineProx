"""Changes to a guest's monitored files and folders go to the persistent layer, not to the disposable one (operator, 2026-10-19).

A guest's OS layer is the disposable overlay that is thrown away and rebuilt; its retained disk (mounted at /home) is what lasts. The folders that matter (sign-ins and saved networks, Bluetooth
pairings, host keys, the AI tools' settings) are therefore bind-mounted from the retained disk over their usual place at every boot, before the services that use them start. The first time,
what the base image already holds there is copied across once; afterwards the retained copy is the only truth and is never re-seeded. A program that changes a file simply writes to the
persistent folder: nothing is synced later, so nothing can be lost between a change and its being kept. Secrets delivered from the vault (/run/baseline-vault) are the exception on purpose:
they stay in RAM, and the vault itself (on the host's own volumes) is what persists.
"""
from __future__ import annotations

import re

STORE = "/home/.baseline-overlay"
READY = "/run/baseline-home-ready"
_PATH = re.compile(r"^(/[A-Za-z0-9._-]+){2,}$")
_FORBIDDEN = ("/run", "/proc", "/sys", "/dev", "/home", "/boot", "/tmp")

MONITORED = (
    "/var/lib/bluetooth",                         # Bluetooth pairings and device settings (sent from the parent host)
    "/etc/NetworkManager/system-connections",     # saved networks and their credentials
    "/etc/ssh",                                   # the machine's host keys, so its identity does not change
    "/var/lib/AccountsService",                   # the owner's account settings
    "/var/lib/ollama",                            # the AI runtime's models and settings
    "/etc/baseline",                              # Baseline's own settings inside the guest
)
BEFORE = ("bluetooth.service", "NetworkManager.service", "ssh.service", "sshd.service", "ollama.service", "accounts-daemon.service")


class PersistenceError(ValueError):
    pass


def check_path(path: str) -> str:
    if (not isinstance(path, str) or not _PATH.fullmatch(path) or ".." in path.split("/")
            or any(path == f or path.startswith(f + "/") for f in _FORBIDDEN)):
        raise PersistenceError(f"{path!r} cannot be kept on the retained disk")
    return path


def subdir_for(path: str) -> str:
    """The folder name on the persistent volume: the same scheme persist_bind_mounts.REDIRECT_PATHS uses on the host (/var/lib/bluetooth -> var-lib-bluetooth), so a guest's overlay and the
    host's USER_ADMIN hold the same thing under the same name, and a pairing or setting carried from the host drops straight in."""
    import persist_bind_mounts as pbm
    return pbm.REDIRECT_PATHS.get(check_path(path)) or path.strip("/").replace("/", "-").lower()


def script(paths=MONITORED) -> str:
    """The boot script: for each folder, seed the retained copy once, then bind it over the usual place. Idempotent; stops without touching anything when the home is not mounted."""
    lines = ["#!/bin/sh", "set -u", f'[ -e {READY} ] || {{ echo "retained home is not ready; nothing changed" >&2; exit 1; }}', f"mkdir -p {STORE}", "keep() {",
             '    place="$1"; kept="$2"',
             '    mkdir -p "$kept" "$place"',
             '    if [ ! -e "$kept/.seeded" ]; then',
             '        [ -n "$(ls -A "$place" 2>/dev/null)" ] && cp -a "$place/." "$kept/"',
             '        : > "$kept/.seeded"',
             "    fi",
             '    mountpoint -q "$place" || mount --bind "$kept" "$place"',
             "}"]
    for raw in paths:
        path = check_path(raw)
        lines.append(f"keep {path} {STORE}/{subdir_for(path)}")
    return "\n".join(lines) + "\n"


def unit(paths=MONITORED) -> str:
    return ("[Unit]\nDescription=Keep monitored folders on the retained disk\nAfter=local-fs.target\nConditionPathExists=" + READY + "\nBefore=" + " ".join(BEFORE) +
            "\n\n[Service]\nType=oneshot\nRemainAfterExit=yes\nExecStart=/usr/local/sbin/baseline-persist-monitored\n\n[Install]\nWantedBy=multi-user.target\n")


def guest_files(paths=MONITORED) -> list:
    """cloud-init write_files entries (the unit is enabled by the seed's runcmd)."""
    return [{"path": "/usr/local/sbin/baseline-persist-monitored", "permissions": "0755", "content": script(paths)},
            {"path": "/etc/systemd/system/baseline-persist-monitored.service", "permissions": "0644", "content": unit(paths)}]
