"""Putting the vault to use where the work happens (operator, 2026-10-19: the vault must be usable on the web applications, on the VMs and on Kasm).

A secret reaches a place only when it was granted to that place: a target is `vm:<name>` (a virtual machine), `kasm` (the Kasm workspaces machine) or `app:<name>` (an application inside a
guest). Delivery writes the granted values into the running guest's RAM, `/run/baseline-vault/<NAME>` (mode 0600), through the guest agent with the value on stdin: it is never in a command
line, a log, a seed image or the guest's disk, and it is gone at the guest's next stop. Programs in the guest read the file (or `baseline-vault-env`, which exports them). A sealed vault that is
locked, a missing secret or an unreachable guest is reported per secret and never stops the rest.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import write_once

GUEST_DIR = "/run/baseline-vault"
_TARGET = re.compile(r"^(kasm|(vm|app):[A-Za-z0-9][A-Za-z0-9._-]{0,62})$")
_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


class GrantError(ValueError):
    pass


class Unavailable(RuntimeError):
    """A secret that cannot be read now (sealed and locked)."""


def _load(path) -> dict:
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return {k: sorted(set(v)) for k, v in data.items() if isinstance(k, str) and _TARGET.fullmatch(k) and isinstance(v, list)} if isinstance(data, dict) else {}


def _save(path, data) -> None:
    write_once.write_if_changed(path, json.dumps({k: sorted(v) for k, v in sorted(data.items()) if v}, indent=1, sort_keys=True) + "\n", mode=0o600)


def _check(target, name) -> None:
    if not isinstance(target, str) or not _TARGET.fullmatch(target):
        raise GrantError("a target is kasm, vm:<name> or app:<name>")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise GrantError("a secret name is capital letters, digits and underscores")


def grant(path, target, name) -> None:
    _check(target, name)
    data = _load(path)
    data[target] = sorted(set(data.get(target, [])) | {name})
    _save(path, data)


def revoke(path, target, name) -> None:
    _check(target, name)
    data = _load(path)
    data[target] = [n for n in data.get(target, []) if n != name]
    _save(path, data)


def granted(path, target) -> list:
    return _load(path).get(target, [])


def deliver(path, target, read_secret, push) -> dict:
    """read_secret(name) -> value | None (may raise Unavailable); push(argv, stdin_bytes) runs a command in the guest. Returns {"delivered": [...], "skipped": {name: reason}}."""
    report = {"delivered": [], "skipped": {}}
    for name in granted(path, target):
        try:
            value = read_secret(name)
        except Unavailable as exc:
            report["skipped"][name] = str(exc)[:120]
            continue
        if not value:
            report["skipped"][name] = "no such secret in the vault"
            continue
        script = f'umask 077; mkdir -p -m 700 {GUEST_DIR}; cat > {GUEST_DIR}/{name}.new && mv -f {GUEST_DIR}/{name}.new {GUEST_DIR}/{name}'
        try:
            push(["sh", "-c", script], value.encode())
        except (OSError, RuntimeError, ValueError) as exc:
            report["skipped"][name] = str(exc)[:120]
            continue
        report["delivered"].append(name)
    return report


# What every guest carries so its programs can use what was delivered: a login-shell export of each delivered secret (so a terminal, a browser started from it and its scripts see them), and
# `baseline-vault NAME` to print one. Both only read /run/baseline-vault, which exists only while the guest runs.
GUEST_FILES = [
    {"path": "/etc/profile.d/baseline-vault.sh", "permissions": "0644", "content":
     f'for f in {GUEST_DIR}/*; do [ -f "$f" ] && [ -r "$f" ] && export "$(basename "$f")=$(cat "$f")"; done 2>/dev/null\n'},
    {"path": "/usr/local/bin/baseline-vault", "permissions": "0755", "content":
     f'#!/bin/sh\n# prints one secret delivered to this machine by the Baseline vault\ncase "$1" in ""|*/*|.*) echo "usage: baseline-vault NAME" >&2; exit 2;; esac\ncat "{GUEST_DIR}/$1"\n'},
]
