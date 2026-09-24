"""Shared helper so every collector reports *why* a field is empty, not
just that it is. Runner already never raises - it returns ok/timed_out/
output_truncated/permission_denied/unavailable on every CommandResult
(runner.py's own contract) - but until now most collectors dropped that
detail on the floor the moment `result.ok` was False, falling back to a
bare None/[]/{} indistinguishable from "genuinely nothing there." This
is what the validator's "every unavailable/timed_out/truncated/denied
category is visibly reported" check depends on.
"""


def note(result, label):
    """None when result is a clean, non-truncated success; otherwise a
    small dict describing what didn't come through, for a collector's
    _collection_notes list."""
    if result.timed_out:
        return {"command": label, "status": "timed_out", "reason": result.reason}
    if result.permission_denied:
        return {"command": label, "status": "permission_denied", "reason": result.reason}
    if result.unavailable:
        return {"command": label, "status": "unavailable", "reason": result.reason}
    if not result.ok:
        return {"command": label, "status": "error", "reason": result.reason or "unknown error"}
    if result.output_truncated:
        return {"command": label, "status": "output_truncated", "reason": "output exceeded max_output_bytes"}
    return None


def notes(*pairs):
    """pairs is (result, label) tuples; returns the non-None notes."""
    return [n for n in (note(result, label) for result, label in pairs) if n is not None]
