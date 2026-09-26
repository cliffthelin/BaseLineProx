"""File-picker broker (Track B3) - scoped to one Baseline-controlled
"exchange" directory rather than a real portal-backed native file-chooser
dialog (which would need a GTK/portal backend this milestone deliberately
isn't adopting). A pragmatic MVP simplification, not a claim that
arbitrary filesystem browsing is solved. See
docs/design/milestone-2-gui-plan.md.

`pick_exchange_file` only ever returns a path for a name it just listed
via `list_exchange_files` in the same call - an explicit allowlist check,
not path sanitization alone, so `../../etc/shadow`-style traversal is
refused by construction, not by pattern-matching the string.
"""
from __future__ import annotations

import posixpath

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:
        def listdir(self, path):
            raise NotImplementedError

DEFAULT_EXCHANGE_DIR = "/var/lib/baseline/gui-exchange"


def list_exchange_files(runner: Runner, exchange_dir: str = DEFAULT_EXCHANGE_DIR) -> list:
    entries = runner.listdir(exchange_dir)
    return sorted(posixpath.basename(str(entry)) for entry in entries)


def pick_exchange_file(runner: Runner, name: str, exchange_dir: str = DEFAULT_EXCHANGE_DIR):
    if name not in list_exchange_files(runner, exchange_dir):
        return None
    return posixpath.join(exchange_dir, name)
