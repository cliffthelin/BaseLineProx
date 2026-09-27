"""Real, Runner-injectable file CRUD for the scripts inbox - a shared
folder scripts get pushed into (from a phone, a laptop, anything with
network + CRUD access) so an operator can run them by hand from a real
Proxmox/Baseline terminal afterward. Per direct instruction: "it's just
files with server and folder access to CRUD."

This module never executes anything itself - it only stores files.
Running a script from the inbox is always a deliberate, manual
operator action at a real terminal, matching this project's "explicit
human decision for anything consequential" principle (PRD SS2/SS6,
the same standard settings_web.py already holds itself to for its own
one destructive trigger).

Lives on USER_PERSISTENCE (drive_installer.py's own BASELINE_VOLUMES
mountpoint) so the inbox survives a reinstall, unlike the disposable
substrate.

Every name is validated as a single, safe, flat filename - no path
separators, no `.`/`..`, no leading dot, bounded length - before it
ever reaches a real path join, so path traversal is refused by
construction, matching gui_brokers.file_picker's own established
discipline for this exact threat, not by trying to enumerate every
traversal trick.
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:
        def makedirs(self, path):
            raise NotImplementedError

        def listdir(self, path):
            raise NotImplementedError

        def path_exists(self, path):
            raise NotImplementedError

        def read_text(self, path):
            raise NotImplementedError

        def write_text_atomic(self, path, content):
            raise NotImplementedError

        def remove(self, path):
            raise NotImplementedError


DEFAULT_INBOX_DIR = "/mnt/USER_PERSISTENCE/scripts_inbox"
MAX_SCRIPT_BYTES = 1_000_000  # generous for a hand-written or phone-dictated script; refuses anything absurd


def inbox_dir_for(persona: str | None = None) -> str:
    """Persona-aware wiring (work-queue item 25, decision record 78).
    `persona=None` (default) reproduces DEFAULT_INBOX_DIR unchanged -
    matches the real, already-deployed plain USER_PERSISTENCE
    partition (decision record 46), so no existing caller is affected.
    A real persona name gives that persona's own scripts_inbox
    subdirectory under drive_installer's USER_PERSISTENCE_<PERSONA>
    mountpoint, so each persona's pushed scripts stay separate -
    matching "the data in each is not at risk for the other"
    (decision record 76)."""
    if persona is None:
        return DEFAULT_INBOX_DIR
    import drive_installer as di
    return f"{di.persona_mountpoint(persona)}/scripts_inbox"

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass
class CrudResult:
    ok: bool
    detail: str = ""


def is_safe_name(name: str) -> bool:
    """A single, flat, safe filename - no separators, no leading dot,
    no `..`, bounded length (1-128 chars). Refused by construction
    (regex + basename equality), not by trying to enumerate every
    traversal trick."""
    if not _SAFE_NAME_RE.match(name):
        return False
    return posixpath.basename(name) == name


def ensure_inbox_dir(runner: Runner, inbox_dir: str = DEFAULT_INBOX_DIR) -> None:
    runner.makedirs(inbox_dir)


def list_scripts(runner: Runner, inbox_dir: str = DEFAULT_INBOX_DIR) -> list:
    ensure_inbox_dir(runner, inbox_dir)
    return sorted(posixpath.basename(str(p)) for p in runner.listdir(inbox_dir))


def read_script(runner: Runner, name: str, inbox_dir: str = DEFAULT_INBOX_DIR) -> str | None:
    if not is_safe_name(name):
        return None
    path = posixpath.join(inbox_dir, name)
    if not runner.path_exists(path):
        return None
    return runner.read_text(path)


def write_script(runner: Runner, name: str, content: str, inbox_dir: str = DEFAULT_INBOX_DIR) -> CrudResult:
    if not is_safe_name(name):
        return CrudResult(False, f"unsafe name: {name!r}")
    if len(content.encode("utf-8")) > MAX_SCRIPT_BYTES:
        return CrudResult(False, f"script exceeds {MAX_SCRIPT_BYTES} bytes")
    ensure_inbox_dir(runner, inbox_dir)
    path = posixpath.join(inbox_dir, name)
    runner.write_text_atomic(path, content)
    return CrudResult(True, f"wrote {name}")


def delete_script(runner: Runner, name: str, inbox_dir: str = DEFAULT_INBOX_DIR) -> CrudResult:
    if not is_safe_name(name):
        return CrudResult(False, f"unsafe name: {name!r}")
    path = posixpath.join(inbox_dir, name)
    if not runner.path_exists(path):
        return CrudResult(False, f"{name} does not exist")
    runner.remove(path)
    return CrudResult(True, f"deleted {name}")
