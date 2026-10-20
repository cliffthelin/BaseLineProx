"""The Wiki and the proposals, tied to the running Kasm (DR263).

`Advice(machine)` keeps the Wiki fresh from the telemetry history, takes in proposals an AI has left in the inbox, and runs the person's decisions: try one (a temporary change with the old values
kept), then keep it or put it back, with Baseline's own before-and-after check beside the person's verdict. `machine` is a KasmSetup (or anything with its read_settings, apply_settings,
telemetry_db, read_record, read_view and layout.admin_dir).
"""
from __future__ import annotations

import time
from pathlib import Path

import kasm_proposals as kp
import kasm_settings_ui as ui
import kasm_telemetry as kt
import kasm_wiki as wiki


class Advice:
    def __init__(self, machine, clock=time.time):
        self.machine, self.clock = machine, clock
        self.root = Path(machine.layout.admin_dir)
        self.store = kp.ProposalStore(self.root / "proposals")

    def _vm(self) -> dict:
        record = self.machine.read_record() or {}
        return {"memory_mb": record.get("memory_mb") or 0, "cpus": record.get("cpus") or 0}

    def _live(self, passphrase=None) -> list:
        read = self.machine.read_settings(passphrase)
        return read["settings"] if read["ok"] else []

    def refresh(self, now=None, passphrase=None) -> dict:
        """Rewrite the Wiki from the history, then take in whatever is in the inbox. Quiet and safe to repeat."""
        now = self.clock() if now is None else now
        live = self._live(passphrase)
        conn = self.machine.telemetry_db()
        try:
            fingerprints = {f for (f,) in conn.execute("SELECT DISTINCT fingerprint FROM events")}
            metrics = {m for (m,) in conn.execute("SELECT DISTINCT metric FROM samples")}
            intake = self.store.ingest(live, fingerprints, metrics, now) if live else {"accepted": [], "rejected": [], "waiting": len(list(self.store.folder("inbox").glob("*")))}
            made = wiki.generate(self.root, conn, self._vm(), live, self.store.known(), self.machine.read_view() or ui.default_shown(), now)
        finally:
            conn.close()
        return {"wiki": made, "proposals": intake}

    def overview(self, now=None) -> dict:
        now = self.clock() if now is None else now
        live = self._live()
        rows = {r["name"]: r for r in live}
        conn = self.machine.telemetry_db()
        try:
            trials = []
            for trial in self.store.list("trial"):
                check = kp.evaluate(conn, trial["expect"], trial["started"], now)
                trials.append({**trial, "check": check})
        finally:
            conn.close()

        def with_changes(p):
            return {**p, "changes": [{"name": n, "title": rows[n]["title"] if n in rows else n, "current": rows[n]["value"] if n in rows else None, "new": v,
                                      "restart": rows[n]["restart"] if n in rows else []} for n, v in p.get("settings", {}).items()]}
        wiki_dir = self.root / "wiki"
        return {"live": bool(live), "pending": [with_changes(p) for p in self.store.list("pending")], "trials": [with_changes(t) for t in trials],
                "archive": sorted(self.store.list("archive"), key=lambda p: p.get("ended") or p.get("received") or 0, reverse=True)[:30],
                "waiting": len(list(self.store.folder("inbox").glob("*"))), "wiki_path": str(wiki_dir), "brief_path": str(wiki_dir / "brief.md"),
                "inbox_path": str(self.store.folder("inbox")), "wiki_ready": (wiki_dir / "brief.md").is_file(),
                "wiki_written": (wiki_dir / "brief.md").stat().st_mtime if (wiki_dir / "brief.md").is_file() else None}

    def try_it(self, ident: str, passphrase=None, now=None) -> dict:
        """Make a pending proposal's setting changes for a trial, keeping the old values. One trial at a time; sizes are advice and cannot be tried."""
        now = self.clock() if now is None else now
        if self.store.list("trial"):
            raise kp.ProposalError("Finish the trial that is running first.")
        proposal = self.store.get("pending", ident)
        if proposal is None:
            raise kp.ProposalError("That proposal is not waiting for a decision.")
        if not proposal["settings"]:
            raise kp.ProposalError("It only recommends a size, which a person changes; there is nothing to try here.")
        result = self.machine.apply_settings(proposal["settings"], passphrase)
        if result["failed"]:
            if result["applied"]:                                       # put back whatever did change; never leave half a proposal in place
                self.machine.apply_settings({a["name"]: a["old"] for a in result["applied"]}, passphrase)
            raise kp.ProposalError("Kasm refused: " + "; ".join(f"{f['title']}: {f['reason']}" for f in result["failed"]))
        if not result["applied"]:
            raise kp.ProposalError("Kasm already has those values.")
        self.store.move(ident, "pending", "trial", started=now, before={a["name"]: a["old"] for a in result["applied"]}, applied={a["name"]: a["new"] for a in result["applied"]},
                        restart=result["restart"])
        return {"started": ident, "restart": result["restart"], "applied": [a["title"] for a in result["applied"]]}

    def finish(self, ident: str, verdict: str, note: str = "", passphrase=None, now=None) -> dict:
        """End a trial with the person's verdict. Better keeps the change; same or worse puts the old values back (a setting that has been changed again since is left alone and said so)."""
        now = self.clock() if now is None else now
        if verdict not in kp.VERDICTS:
            raise kp.ProposalError("Say better, same or worse.")
        trial = self.store.get("trial", ident)
        if trial is None:
            raise kp.ProposalError("That trial is not running.")
        conn = self.machine.telemetry_db()
        try:
            check = kp.evaluate(conn, trial["expect"], trial["started"], now)
        finally:
            conn.close()
        kept, left = verdict == "better", []
        if not kept:
            live = {r["name"]: r["value"] for r in self._live(passphrase)}
            back = {n: old for n, old in trial["before"].items() if live.get(n) == trial["applied"].get(n)}
            left = [n for n in trial["before"] if n not in back]       # changed by someone since: not ours to undo
            if back:
                undone = self.machine.apply_settings(back, passphrase)
                if undone["failed"]:
                    raise kp.ProposalError("Kasm would not put the old values back: " + "; ".join(f"{f['title']}: {f['reason']}" for f in undone["failed"]))
        archived = self.store.move(ident, "trial", "archive", verdict=verdict, kept=kept, check=check, ended=now, note=kp.kt.redact(note or "")[:500], left_as_found=left,
                                   recipe_settings=trial["settings"] if kept else None)
        return archived

    def archive(self, ident: str, note: str = "", now=None) -> dict:
        return self.store.archive_unused(ident, note, self.clock() if now is None else now)
