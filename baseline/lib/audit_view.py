"""Read-only view of the append-only audit log (hitl.AuditFile). Never writes, never shows secret-looking fields."""
from __future__ import annotations

import json
from pathlib import Path

_HIDDEN = ("secret", "password", "passphrase", "token", "hash", "key", "cookie")
MAX_TAIL_BYTES = 1_000_000


def read_tail(path, limit: int = 200) -> list:
    """The last `limit` records, newest first. Unparseable lines are skipped; a missing file is an empty list."""
    try:
        with open(Path(path), "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - MAX_TAIL_BYTES))
            raw = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    records = []
    for line in raw.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append({k: v for k, v in record.items() if not any(h in k.lower() for h in _HIDDEN)})
    return list(reversed(records[-limit:]))
