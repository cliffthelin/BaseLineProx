"""Proposed Kasm changes: where they come from, how they are checked, tried, judged and archived (DR263; operator 2026-10-17).

An AI (or a person) that has read the Wiki drops a proposal file into proposals/inbox/. Baseline validates it against Kasm's own live settings (typed, no secrets, no unknown names, every
concern it cites must exist, it must say how success is measured), then it waits for a person. A person may TRY it: the changes are made through Kasm's own admin API with the old values kept,
so a trial is a temporary change with a certain way back. When the person says better, same or worse, Baseline also compares the measure the proposal named before and after, and the whole thing
goes to the archive with both opinions. Nothing is applied without a person, only one trial runs at a time, and a size recommendation is only ever advice.

Folders under proposals/: inbox (raw files dropped by an AI), pending, trial, archive.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import time
from pathlib import Path

import kasm_settings_ui as ui
import kasm_telemetry as kt

STATES = ("inbox", "pending", "trial", "archive")
MAX_PENDING = 5
ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")
DIRECTIONS = ("up", "down")
VERDICTS = ("better", "same", "worse")
SIZE_LIMITS = {"memory_mb": (2048, 262144), "cpus": (1, 64)}
MIN_TRIAL_S = 3600                     # a check needs at least an hour of the new setting
MIN_SAMPLES = 5


class ProposalError(ValueError):
    pass


def _text(value, name, limit, required=True) -> str:
    if not isinstance(value, str) or (required and not value.strip()):
        raise ProposalError(f"{name} must be text" if required else f"{name} must be text if given")
    return kt.redact(value.strip())[:limit]


def validate(raw, live: list, fingerprints: set, metrics: set) -> dict:
    """The proposal in its stored shape, or ProposalError saying what is wrong. `live` is Kasm's own settings list."""
    if not isinstance(raw, dict):
        raise ProposalError("a proposal is a JSON object")
    settings, sizes = raw.get("settings") or {}, raw.get("sizes") or {}
    if not isinstance(settings, dict) or not isinstance(sizes, dict):
        raise ProposalError("settings and sizes are name to value objects")
    if not settings and not sizes:
        raise ProposalError("it proposes no setting and no size")
    clean_settings = {}
    if settings:
        try:
            plan = ui.plan(live, {str(k): v for k, v in settings.items()})
        except ui.SettingsError as exc:
            raise ProposalError(str(exc)) from None
        if not plan:
            raise ProposalError("every value it proposes is what Kasm already has")
        clean_settings = {c["name"]: c["new"] for c in plan}
        clean_settings.update({k: str(v) for k, v in settings.items() if k not in clean_settings})   # unchanged ones stay in the record so a duplicate is recognised
    clean_sizes = {}
    for key, value in sizes.items():
        if key not in SIZE_LIMITS or not isinstance(value, int) or isinstance(value, bool) or not SIZE_LIMITS[key][0] <= value <= SIZE_LIMITS[key][1]:
            raise ProposalError(f"size {key} is not one of memory_mb, cpus, or its value is out of range")
        clean_sizes[key] = value
    concerns = raw.get("concerns") or []
    if not isinstance(concerns, list) or not all(isinstance(c, str) for c in concerns):
        raise ProposalError("concerns is a list of fingerprints")
    unknown = [c for c in concerns if c not in fingerprints]
    if unknown:
        raise ProposalError(f"it cites a concern that does not exist: {unknown[0]}")
    expect = raw.get("expect")
    if not isinstance(expect, dict) or expect.get("direction") not in DIRECTIONS:
        raise ProposalError("it must say how success is measured: expect with a direction of up or down")
    if "metric" in expect and expect["metric"] not in metrics:
        raise ProposalError(f"expect names a measure that has no data: {expect['metric']}")
    if "concern" in expect and (expect["concern"] not in fingerprints or expect["direction"] != "down"):
        raise ProposalError("expect a concern to go down, naming one that exists")
    if ("metric" in expect) == ("concern" in expect):
        raise ProposalError("expect names either a metric or a concern")
    return {"title": _text(raw.get("title"), "title", 120), "rationale": _text(raw.get("rationale"), "rationale", 2000), "concerns": concerns,
            "settings": clean_settings, "sizes": clean_sizes, "expect": {k: expect[k] for k in ("metric", "concern", "direction") if k in expect},
            "rollback": _text(raw.get("rollback", ""), "rollback", 500, required=False)}


def _median(values):
    return statistics.median(values) if values else None


def evaluate(conn, expect: dict, started: float, now: float) -> dict:
    """Did the measure the proposal named move the way it said? Compares the time since the trial began with an equal time before it. Plain statuses, never a guess from too little."""
    span = now - started
    if span < MIN_TRIAL_S:
        return {"status": "too-early", "text": f"Too early to tell: the trial has run {span / 60:.0f} minutes, and a check needs at least an hour."}
    before_from = started - span
    if "metric" in expect:
        metric = expect["metric"]
        before = [v for (v,) in conn.execute("SELECT value FROM samples WHERE metric=? AND ts>=? AND ts<?", (metric, before_from, started))]
        after = [v for (v,) in conn.execute("SELECT value FROM samples WHERE metric=? AND ts>=? AND ts<=?", (metric, started, now))]
        if len(before) < MIN_SAMPLES or len(after) < MIN_SAMPLES:
            return {"status": "no-data", "text": f"Not enough measurements of {metric} either side of the start ({len(before)} before, {len(after)} after)."}
        b, a = _median(before), _median(after)
        change = (a - b) / abs(b) if b else (0.0 if a == b else float("inf"))
        wanted = change if expect["direction"] == "up" else -change
        status = "improved" if wanted >= 0.10 else "worse" if wanted <= -0.10 else "no-clear-change"
        return {"status": status, "before": b, "after": a, "text": f"{metric}: median {b:.1f} before, {a:.1f} after ({'improved' if status == 'improved' else 'worse' if status == 'worse' else 'no clear change'})."}
    fp = expect["concern"]
    before_n = conn.execute("SELECT COUNT(*) FROM events WHERE fingerprint=? AND ts>=? AND ts<?", (fp, before_from, started)).fetchone()[0]
    after_n = conn.execute("SELECT COUNT(*) FROM events WHERE fingerprint=? AND ts>=? AND ts<=?", (fp, started, now)).fetchone()[0]
    if before_n == 0:
        return {"status": "no-data", "text": "The problem was not seen in the time before the trial, so there is nothing to compare."}
    status = "improved" if after_n <= before_n * 0.5 else "worse" if after_n >= before_n * 1.5 else "no-clear-change"
    return {"status": status, "before": before_n, "after": after_n, "text": f"The problem was seen {before_n} time(s) before and {after_n} time(s) during the trial ({status.replace('-', ' ')})."}


class ProposalStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def folder(self, state: str) -> Path:
        path = self.root / state
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _write(self, state: str, proposal: dict):
        path = self.folder(state) / f"{proposal['id']}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(proposal, indent=1))
        os.replace(tmp, path)

    def list(self, state: str) -> list:
        out = []
        for path in sorted(self.folder(state).glob("*.json")):
            try:
                item = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(item, dict):
                out.append(item)
        return out

    def get(self, state: str, ident: str):
        if not ID.match(ident or ""):
            return None
        return next((p for p in self.list(state) if p.get("id") == ident), None)

    def move(self, ident: str, source: str, target: str, **updates) -> dict:
        proposal = self.get(source, ident)
        if proposal is None:
            raise ProposalError(f"there is no {source} proposal called {ident}")
        proposal.update(updates, state=target)
        self._write(target, proposal)
        (self.folder(source) / f"{ident}.json").unlink(missing_ok=True)
        return proposal

    def known(self) -> list:
        return [p for state in ("pending", "trial", "archive") for p in self.list(state)]

    def ingest(self, live: list, fingerprints: set, metrics: set, now: float) -> dict:
        """Check what is in the inbox. A good proposal becomes pending (up to MAX_PENDING at once; the rest wait in the inbox); a bad one, or one that repeats an earlier change, goes to the
        archive as rejected with the reason, so the AI that wrote it can see why."""
        accepted, rejected = [], []
        for path in sorted(self.folder("inbox").glob("*")):
            ident = path.stem
            reason = None
            try:
                if not ID.match(ident) or path.suffix != ".json":
                    raise ProposalError("the file name must be lowercase letters, digits and hyphens, ending .json")
                if path.stat().st_size > 20000:
                    raise ProposalError("the file is too large")
                proposal = validate(json.loads(path.read_text()), live, fingerprints, metrics)
                same = next((p for p in self.known() if p.get("settings") and p["settings"] == proposal["settings"] and p.get("sizes", {}) == proposal["sizes"]), None)
                if same is not None:
                    raise ProposalError(f"the same change is already here as {same['id']} ({same.get('verdict') or same.get('state')})")
                if self.get("pending", ident) or self.get("trial", ident) or self.get("archive", ident):
                    raise ProposalError("a proposal with that id already exists")
                if len(self.list("pending")) >= MAX_PENDING:
                    continue                                        # leave it for later; nothing is lost
                self._write("pending", {"id": ident, "state": "pending", "received": now, **proposal})
                accepted.append(ident)
            except (ProposalError, ValueError, OSError) as exc:
                reason = str(exc) if not isinstance(exc, ValueError) or isinstance(exc, ProposalError) else "the file is not valid JSON"
            if reason is not None:
                if ID.match(ident) and not self.get("archive", ident):
                    self._write("archive", {"id": ident, "state": "archive", "verdict": "rejected", "reason": kt.redact(reason)[:300], "received": now, "title": ident, "settings": {}, "concerns": []})
                rejected.append({"id": ident, "reason": reason})
            path.unlink(missing_ok=True)
        return {"accepted": accepted, "rejected": rejected, "waiting": len(list(self.folder("inbox").glob("*")))}

    def archive_unused(self, ident: str, note: str, now: float) -> dict:
        return self.move(ident, "pending", "archive", verdict="not tried", note=kt.redact(note or "")[:500], ended=now)
