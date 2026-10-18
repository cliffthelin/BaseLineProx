"""Remote authorization of a full rebuild (a wipe of a named drive), decided by a root service and approved with a one-time code.

The flow, which works from any device that can reach the person's chat or shell:
  1. `request <target>`   the service records a pending request and returns its id and a one-time code (valid 15 minutes);
  2. the person sends the code back from wherever they are;
  3. `approve <id> <code>`  the service checks the code (3 tries, single use, not expired) and only then queues the rebuild of exactly that target.
Every message arrives as a small file in an inbox the person's account can write; the service (root) keeps all state in its own directory, so a request, an approval or a code cannot be forged by
writing files. Only the SHA-256 of a code is kept. The target must be a name in the operator's own drives file; the drive's serial is read there at run time and is never stored here.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from pathlib import Path

TTL_SECONDS = 15 * 60
MAX_TRIES = 3
_TARGET = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_ID = re.compile(r"^[a-f0-9]{16}$")


def _hash(code: str, request_id: str) -> str:
    return hashlib.sha256(f"{request_id}:{code}".encode()).hexdigest()


class Authority:
    def __init__(self, state_dir, drives: dict, *, now=time.time):
        self.dir = Path(state_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.drives, self.now = dict(drives), now

    def _path(self, request_id):
        return self.dir / f"{request_id}.json"

    def _load(self, request_id):
        if not _ID.match(str(request_id)):
            return None
        try:
            return json.loads(self._path(request_id).read_text())
        except (OSError, ValueError):
            return None

    def _save(self, req):
        self._path(req["id"]).write_text(json.dumps(req))

    def request(self, target: str) -> dict:
        if not _TARGET.match(str(target)) or target not in self.drives:
            return {"ok": False, "error": f"{target!r} is not a drive this machine knows; known: {', '.join(sorted(self.drives)) or 'none'}"}
        if any(r["target"] == target and r["state"] in ("approved", "running") for r in self._all()):
            return {"ok": False, "error": f"a rebuild of {target} is already approved or running"}
        request_id, code = secrets.token_hex(8), f"{secrets.randbelow(10**8):08d}"
        self._save({"id": request_id, "target": target, "state": "pending", "tries": 0, "code_hash": _hash(code, request_id), "expires": self.now() + TTL_SECONDS})
        return {"ok": True, "id": request_id, "code": code, "target": target, "expires_in_s": TTL_SECONDS}

    def approve(self, request_id: str, code: str) -> dict:
        req = self._load(request_id)
        if req is None or req["state"] != "pending":
            return {"ok": False, "error": "no such pending request"}
        if self.now() > req["expires"]:
            req["state"] = "expired"
            self._save(req)
            return {"ok": False, "error": "that request has expired; make a new one"}
        if not hmac.compare_digest(_hash(str(code).strip(), req["id"]), req["code_hash"]):
            req["tries"] += 1
            if req["tries"] >= MAX_TRIES:
                req["state"] = "refused"
            self._save(req)
            return {"ok": False, "error": "the code is wrong" + ("; request closed after too many tries" if req["state"] == "refused" else "")}
        req["state"] = "approved"
        req["approved_at"] = self.now()
        self._save(req)
        return {"ok": True, "id": req["id"], "target": req["target"], "state": "approved"}

    def _all(self):
        out = []
        for f in sorted(self.dir.glob("*.json")):
            try:
                out.append(json.loads(f.read_text()))
            except (OSError, ValueError):
                continue
        return out

    def take_approved(self):
        """The next approved request, marked running so it is handed out once; None when there is none."""
        for req in self._all():
            if req["state"] == "approved":
                req["state"] = "running"
                self._save(req)
                return req
        return None

    def finish(self, request_id: str, exit_code: int):
        req = self._load(request_id)
        if req:
            req.update(state="done" if exit_code == 0 else "failed", exit_code=exit_code, finished_at=self.now())
            self._save(req)

    def status(self) -> list:
        return [{k: r.get(k) for k in ("id", "target", "state", "exit_code")} for r in self._all()]

    def serial_for(self, target: str) -> str:
        return str(self.drives[target])
