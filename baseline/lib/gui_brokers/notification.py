"""Notification broker (Track B3) - MVP scope per
docs/design/milestone-2-gui-plan.md: durably logs the request (same JSONL
event pattern network.py's EVENT_LOG already uses) and returns success. No
visual notification UI yet - no notification daemon exists in this
minimal cage session; a stub at "minimal, testable level," not a claim
that visual notifications are solved.
"""
from __future__ import annotations

import json
import time

try:
    from repair import Runner  # type: ignore
except ImportError:  # pragma: no cover - direct-script execution fallback
    class Runner:
        def append_text(self, path, content):
            raise NotImplementedError

NOTIFICATION_LOG = "/var/log/baseline/gui_notifications.jsonl"


def notify(runner: Runner, *, app_id: str, summary: str, body: str, log_path: str = NOTIFICATION_LOG) -> bool:
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "app_id": app_id,
        "summary": summary,
        "body": body,
    }
    runner.append_text(log_path, json.dumps(rec) + "\n")
    return True
