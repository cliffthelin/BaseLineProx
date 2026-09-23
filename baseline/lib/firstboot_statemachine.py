"""First-boot state machine (Gate E) - durable, tty1-owning wrapper
around `firstboot_network_repair.py`'s already-real discover -> propose
-> indefinite-CONFIRM -> apply -> verify flow.

Promoted from `experiments/m0-inv6/firstboot_statemachine.py` (decision
record 06), narrowed per that record's own scope note: the general
multi-action shape (firewall/handoff/tether) stays out of scope here -
this wraps exactly one real action, network repair, the same one
`firstboot_network_repair.py` already implements per decision record
12. The CONFIRM-gate discipline itself (no timeout, no default, EOF
never confirms) is not reimplemented here - it lives in and is reused
from `firstboot_network_repair.wait_for_confirmation`, unchanged.

What this module adds on top of that existing flow, matching decision
record 06's addendum-corrected prototype exactly:

- A durable completion marker (fsync file + fsync containing directory
  + atomic rename - the same pattern `setup_intent.record_consumption`
  already uses) so a committed run never re-triggers automatically,
  checked as the very first action before any discovery or side effect.
- A journal entry recording the outcome, for post-hoc diagnosis.

Deliberately NOT re-implemented here (real risk of drifting from the
already-proven, already-tested logic): discovery, diagnosis, the
exact-diff tty1 proposal text, the CONFIRM-gate itself, and the
apply/verify call - all delegated to `firstboot_network_repair`
directly, imported and called, never duplicated.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path

import firstboot_network_repair as fbnr
import repair

STATE_DIR = Path("/var/lib/baseline-firstboot")
JOURNAL_PATH = STATE_DIR / "journal.json"
COMPLETE_MARKER = STATE_DIR / "complete"


def _durable_write(path: Path, content: str) -> None:
    """fsync the file AND its containing directory before the write is
    considered durable - matches setup_intent.record_consumption's
    proven pattern. A crash right after this call cannot leave a
    half-written or not-yet-visible marker/journal entry."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".tmp-{secrets.token_hex(8)}"
    with open(tmp, "w") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    dir_fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def already_completed(state_dir: Path = STATE_DIR) -> str | None:
    """Returns the completion timestamp if a previous run already
    committed, else None. Checked first, before any discovery or side
    effect - even a maliciously or accidentally re-triggered service
    start cannot cause work to redo past a real prior commit."""
    marker = state_dir / "complete"
    if marker.exists():
        return marker.read_text().strip()
    return None


def record_journal_entry(outcome: dict, state_dir: Path = STATE_DIR) -> None:
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **outcome}
    journal_path = state_dir / "journal.json"
    history = []
    if journal_path.exists():
        try:
            history = json.loads(journal_path.read_text()).get("history", [])
        except (json.JSONDecodeError, OSError):
            history = []
    history.append(entry)
    _durable_write(journal_path, json.dumps({"history": history}, indent=2))


def mark_complete(state_dir: Path = STATE_DIR) -> None:
    _durable_write(state_dir / "complete", time.strftime("%Y-%m-%dT%H:%M:%S") + "\n")


def print_tty1(msg: str) -> None:
    print(msg, flush=True)


def run(runner: repair.Runner, *, state_dir: Path = STATE_DIR, stdin=None,
        print_fn=print_tty1, check_lifeline_fn=None) -> dict:
    """The full Gate E flow. Returns the same result shape
    `firstboot_network_repair.run_first_boot_network_repair` returns,
    plus `already_completed` when a prior run's marker short-circuits
    this call entirely."""
    completed_at = already_completed(state_dir)
    if completed_at is not None:
        print_fn(f"[baseline-firstboot] previous run already completed at {completed_at} - not re-triggering.")
        return {"action": "already_completed", "completed_at": completed_at, "package_install_allowed": True}

    result = fbnr.run_first_boot_network_repair(
        runner, requested_by="firstboot-statemachine", stdin=stdin,
        print_fn=print_fn, check_lifeline_fn=check_lifeline_fn,
    )

    record_journal_entry({k: v for k, v in result.items() if k != "result"} |
                          ({"repair_outcome": result["result"].outcome, "repair_detail": result["result"].detail}
                           if "result" in result and hasattr(result["result"], "outcome") else {}),
                          state_dir)

    # Only a genuinely successful outcome (nothing to do, or a real
    # confirmed-and-verified repair) commits. "refused" and "declined"
    # must be retryable on the next explicit boot/trigger, not locked
    # out by a marker that implies success.
    if result.get("package_install_allowed") and result.get("action") in ("none", "replace", "additive"):
        mark_complete(state_dir)
        print_fn("[baseline-firstboot] COMMITTED. Marker written - will not re-run automatically.")

    print_fn("[baseline-firstboot] state machine run finished.")
    return result


def main() -> int:
    result = run(repair.RealRunner())
    return 0 if result.get("package_install_allowed") else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
