"""Deliver notifications through the session's real notification service.

The audit log records delivery acceptance, not proof that a person saw it.
A missing notify-send executable or session service is a delivery failure.
"""
from __future__ import annotations

import json
import time

from repair import Runner

NOTIFICATION_LOG = "/var/log/baseline/gui_notifications.jsonl"


def notify(runner: Runner, *, app_id: str, summary: str, body: str, log_path: str = NOTIFICATION_LOG) -> bool:
    proc = runner.run(["notify-send", "--app-name", app_id, "--", summary, body], timeout=5)
    delivered = proc.returncode == 0
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "app_id": app_id,
        "summary": summary,
        "body": body,
        "delivered": delivered,
        "detail": proc.stderr.strip() if not delivered else "",
    }
    runner.append_text(log_path, json.dumps(rec) + "\n")
    return delivered
