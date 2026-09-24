"""Bounded, dedup-by-signature event logging.

The pattern every loop that might repeat an identical condition
indefinitely must use instead of one log record per occurrence: a
repeated condition must consume bounded resources regardless of how
long it continues. This module is the reusable primitive for that -
used directly by tools/scan_denylist.py's own operational logging
(file-read errors, oversized-file skips), and intended as the template
for any future Baseline diagnostic ledger with the same shape of
problem (a diagnostic control plane cannot remain trustworthy if its
own diagnostics can become a denial-of-service condition).

For each distinct event signature:
  1. The first occurrence is recorded in full, with detail.
  2. A small, fixed number of early repetitions are also recorded.
  3. Further identical repetitions are suppressed entirely - only an
     in-memory counter advances, no record is appended.
  4. A periodic summary record is appended every `summary_interval`-th
     occurrence (so a very long-running condition still surfaces
     progress, without one record per occurrence).
  5. finalize() returns exactly one final summary per signature,
     regardless of how many times it actually occurred - the total
     number of *records* (from both the early/periodic stream and the
     final summary) is bounded by a small constant per signature, never
     by the occurrence count.

Never includes matched/sensitive values itself - callers control what
goes in `detail`, and this module makes no assumption about its
content beyond "safe to keep in memory and to print."
"""
import time

DEFAULT_EARLY_REPETITIONS = 3
DEFAULT_SUMMARY_INTERVAL = 1000


class BoundedEventLog:
    def __init__(self, early_repetitions=DEFAULT_EARLY_REPETITIONS,
                 summary_interval=DEFAULT_SUMMARY_INTERVAL, clock=time.time):
        self.early_repetitions = early_repetitions
        self.summary_interval = summary_interval
        self._clock = clock
        self._state = {}  # signature -> {count, first_seen, last_seen, emitted}
        self.records = []  # bounded - every record actually emitted, in order

    def record(self, signature, detail=None):
        """Call once per occurrence of `signature`. Returns True if this
        call produced a visible record (occurrence/repetition/periodic
        summary), False if it was suppressed (counted, not recorded)."""
        now = self._clock()
        st = self._state.get(signature)
        if st is None:
            st = {"count": 0, "first_seen": now, "last_seen": now, "emitted": 0}
            self._state[signature] = st
        st["count"] += 1
        st["last_seen"] = now

        if st["count"] <= 1 + self.early_repetitions:
            kind = "occurrence" if st["count"] == 1 else "repetition"
            self.records.append({"signature": signature, "kind": kind,
                                  "occurrence_number": st["count"], "detail": detail})
            st["emitted"] += 1
            return True
        if self.summary_interval and st["count"] % self.summary_interval == 0:
            self.records.append({"signature": signature, "kind": "periodic_summary",
                                  "count_so_far": st["count"]})
            st["emitted"] += 1
            return True
        return False

    def count(self, signature):
        st = self._state.get(signature)
        return st["count"] if st else 0

    def finalize(self):
        """One final summary per distinct signature - the "18,421
        occurrences over 64 minutes" line, never a per-occurrence
        record. Safe to call more than once (idempotent, read-only)."""
        summaries = []
        for signature, st in self._state.items():
            summaries.append({
                "event_signature": signature,
                "first_seen": st["first_seen"],
                "last_seen": st["last_seen"],
                "count": st["count"],
                "examples_retained": min(1 + self.early_repetitions, st["count"]),
                "suppressed": max(0, st["count"] - st["emitted"]),
            })
        return summaries

    @property
    def total_emitted_records(self):
        """The actual bound this whole module exists to enforce - must
        stay small even when total occurrences across all signatures
        is huge."""
        return len(self.records)
