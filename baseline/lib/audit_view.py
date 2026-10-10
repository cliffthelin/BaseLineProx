"""Read-only view of the append-only audit log (hitl.AuditFile). Never writes, never shows secret-looking fields."""
from __future__ import annotations

import json
from pathlib import Path

_HIDDEN = ("secret", "password", "passphrase", "token", "hash", "key", "cookie")
MAX_TAIL_BYTES = 1_000_000


class AuditReadError(RuntimeError):
    """The audit log could not be read; it is not an empty history."""


def read_tail(path, limit: int = 200) -> list:
    """The last `limit` intact records, newest first; corruption is unavailable, never silently skipped."""
    if type(limit) is not int or limit < 1:
        raise ValueError('audit tail limit must be a positive integer')
    try:
        with open(Path(path), "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            offset=max(0,size-MAX_TAIL_BYTES)
            f.seek(offset)
            raw=f.read(MAX_TAIL_BYTES)
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise AuditReadError(f"audit log unavailable at {path}: {exc}") from exc
    if offset:
        first_complete=raw.find(b'\n')
        if first_complete<0:
            raise AuditReadError('audit tail contains no complete record boundary')
        raw=raw[first_complete+1:]
    if raw and not raw.endswith(b'\n'):
        raise AuditReadError('audit log ends with an incomplete record')
    try:
        decoded=raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise AuditReadError('audit log contains invalid UTF-8') from exc
    records = []
    for index,line in enumerate(decoded.splitlines(),1):
        if not line.strip():
            raise AuditReadError(f'audit log contains an empty record at tail line {index}')
        try:
            record = json.loads(line)
        except ValueError as exc:
            raise AuditReadError(f'audit log contains malformed JSON at tail line {index}') from exc
        if not isinstance(record,dict):
            raise AuditReadError(f'audit log record at tail line {index} is not an object')
        records.append({k: v for k, v in record.items() if not any(h in k.lower() for h in _HIDDEN)})
    return list(reversed(records[-limit:]))
