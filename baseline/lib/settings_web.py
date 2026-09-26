"""Post-install settings web UI (PRD SS5.16).

A persistent, re-enterable, LAN-scoped web surface so a user is never
forced to redo their entire install just to change or review a
setting. Two flows are carried to completion automatically:

1. **Login with the existing root username/password** -> review every
   current setting on one page -> edit a section -> that section's own
   existing confirm-then-apply mechanism re-runs for just that piece.
2. **Create a new account** -> build a complete fresh configuration
   from a blank form -> explicitly initiate a rebuild from it. This is
   the only destructive trigger this module exposes, and it is gated
   by `RebuildEligibility` - refused by default. Real physical-drive
   eligibility checking is explicitly out of scope before Milestone 3
   (PRD SS4/SS6); this module never assumes eligibility, it only ever
   asks an injected checker.

Anything that isn't one of those two flows - an unrecognized section,
a rebuild request that isn't eligible, an ambiguous action - is
**handed off**, not silently completed and not silently refused: the
response says exactly what happened and that a human must act next,
matching PRD SS2/SS6's "explicit human decision for anything
consequential" principle.

Reuses this project's established patterns rather than inventing new
ones: `http.server.HTTPServer`/`BaseHTTPRequestHandler` (the same
stdlib-only approach `drive_setup_answer.py`'s `EphemeralAnswerServer`
already uses and has real-TLS-socket test coverage for), and
Runner-style dependency injection (`PasswordVerifier`, `SettingsSource`,
`SectionApplier`, `RebuildEligibility`, `RebuildTrigger`) so every path
is unit-testable with fakes, no real root, no real hardware - the same
discipline `repair.py`'s `Runner`/`FakeRunner` established.
"""
from __future__ import annotations

import http.server
import json
import secrets
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs


def _sha512crypt(password: str, salt: str) -> str:
    """SHA-512-crypt via `openssl passwd -6` - the stdlib `crypt`
    module was removed in Python 3.13, and this project already has a
    proven, real subprocess call doing exactly this in
    drive_setup_answer.hash_password_sha512crypt; duplicated as a
    small standalone helper here rather than importing across modules
    that aren't otherwise related, to keep this file runnable on its
    own for local evaluation."""
    argv = ["openssl", "passwd", "-6", "-salt", salt, "-stdin"]
    proc = subprocess.run(argv, input=(password + "\n").encode(), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, check=True)
    return proc.stdout.decode("ascii").strip()


def _new_salt() -> str:
    return secrets.token_hex(8)


# ---------------------------------------------------------------------------
# Injectable boundaries - real implementations are thin, fakes drive tests.
# ---------------------------------------------------------------------------

class PasswordVerifier:
    """Verifies a username/password pair against the real system
    account. The real implementation needs root (reads /etc/shadow via
    `spwd`) - deliberately not implemented as a default here, so a test
    or a caller without root privilege never silently gets a real
    (and therefore unrunnable) check; they must pass a real verifier
    explicitly."""

    def verify(self, username: str, password: str) -> bool:
        raise NotImplementedError


class SettingsSource:
    """Aggregates the current system's settings for the review page.
    The real implementation calls into `hardware.collect()`,
    `network.list_interfaces()`/`check_lifeline()`, and handoff/tether
    status; kept as an injectable boundary so the page layout and
    auth/session logic are testable without real hardware."""

    def current_settings(self) -> dict:
        raise NotImplementedError


@dataclass
class ApplyResult:
    applied: bool
    detail: str


class SectionApplier:
    """Re-applies one settings section's edited values, reusing that
    section's own existing confirm-then-apply mechanism (PRD SS5.10's
    firewall transaction, SS5.13's handoff transaction, etc.) - this
    module never re-implements those mechanisms, it only calls them.
    `KNOWN_SECTIONS` is the explicit allow-list (PRD SS7: "All GUI/TUI
    inputs validated against an explicit allow-list before
    interpolation") - an unknown section name is refused before this
    class is ever reached."""

    def apply(self, section: str, new_values: dict) -> ApplyResult:
        raise NotImplementedError


class RebuildEligibility:
    """Answers exactly one question: is the given target eligible for
    a destructive rebuild right now? Defaults are never assumed by
    this module - only an explicit injected checker's answer is
    trusted, and the checker itself is responsible for enforcing PRD
    SS4/SS6 (image/virtual-disk only through Milestone 2; a real
    physical drive needs the full SS6 gate, never a shortcut through
    this page)."""

    def is_eligible(self, target: str) -> tuple[bool, str]:
        """Returns (eligible, reason)."""
        raise NotImplementedError


class RebuildTrigger:
    """Performs the actual rebuild once `RebuildEligibility` has said
    yes. Kept separate from the eligibility check itself so a test can
    prove the trigger is never called when eligibility says no."""

    def rebuild(self, target: str, config: dict) -> ApplyResult:
        raise NotImplementedError


KNOWN_SECTIONS = frozenset({
    "network", "firewall", "tether", "ssh", "handoff", "diagnostics",
})


# ---------------------------------------------------------------------------
# Session state - a real (in-memory, TTL-bound) login session, not the
# single-use answer-file session drive_setup_answer.py uses.
# ---------------------------------------------------------------------------

@dataclass
class LoginSession:
    token: str
    username: str
    created: float
    ttl_s: float = 1800.0

    def expired(self, now: float) -> bool:
        return now > self.created + self.ttl_s


@dataclass
class SessionStore:
    sessions: dict = field(default_factory=dict)

    def create(self, username: str, now: float) -> LoginSession:
        token = secrets.token_urlsafe(32)
        session = LoginSession(token=token, username=username, created=now)
        self.sessions[token] = session
        return session

    def get(self, token: str, now: float) -> LoginSession | None:
        session = self.sessions.get(token)
        if session is None:
            return None
        if session.expired(now):
            del self.sessions[token]
            return None
        return session


@dataclass
class PendingRebuildAccount:
    """A new account's full-fresh-config draft, built from a blank
    form under SS5.16's second flow. Not applied anywhere until
    `initiate_rebuild` succeeds against `RebuildEligibility`."""
    username: str
    password_hash: str
    config: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# The response shape every route returns - explicit about which of the
# three outcomes happened, so "handed off" can never be confused with
# "succeeded" or "refused" by a caller only checking an HTTP status code.
# ---------------------------------------------------------------------------

@dataclass
class RouteResult:
    outcome: str  # "applied" | "refused" | "handed_off"
    status: int
    body: dict


def handle_login(verifier: PasswordVerifier, sessions: SessionStore,
                  username: str, password: str, now: float) -> RouteResult:
    if verifier.verify(username, password):
        session = sessions.create(username, now)
        return RouteResult("applied", 200, {"token": session.token})
    # Deliberately identical response shape/timing-irrelevant message
    # for "no such user" and "wrong password" - no username enumeration.
    return RouteResult("refused", 401, {"error": "invalid credentials"})


def handle_settings_view(sessions: SessionStore, source: SettingsSource,
                          token: str, now: float) -> RouteResult:
    session = sessions.get(token, now)
    if session is None:
        return RouteResult("refused", 401, {"error": "not authenticated"})
    return RouteResult("applied", 200, {"settings": source.current_settings()})


def handle_settings_edit(sessions: SessionStore, applier: SectionApplier,
                          token: str, section: str, new_values: dict,
                          now: float) -> RouteResult:
    session = sessions.get(token, now)
    if session is None:
        return RouteResult("refused", 401, {"error": "not authenticated"})
    if section not in KNOWN_SECTIONS:
        # Not one of the two safe flows this module completes
        # automatically - hand off rather than guess what an unknown
        # section name should do.
        return RouteResult(
            "handed_off", 409,
            {"reason": f"section {section!r} is not on the known-settings "
                       "allow-list; no automatic action taken",
             "known_sections": sorted(KNOWN_SECTIONS)},
        )
    result = applier.apply(section, new_values)
    if result.applied:
        return RouteResult("applied", 200, {"detail": result.detail})
    return RouteResult("refused", 422, {"detail": result.detail})


def handle_new_account(hasher, username: str, password: str) -> RouteResult:
    """`hasher` is a callable(password: str) -> str, reusing
    drive_setup_answer.hash_password_sha512crypt-shaped injection
    rather than hardcoding a hashing scheme here."""
    if not username or not password:
        return RouteResult("refused", 400, {"error": "username and password required"})
    account = PendingRebuildAccount(username=username, password_hash=hasher(password))
    return RouteResult("applied", 200, {"account": account.username})


def handle_rebuild(eligibility: RebuildEligibility, trigger: RebuildTrigger,
                    target: str, config: dict) -> RouteResult:
    eligible, reason = eligibility.is_eligible(target)
    if not eligible:
        # The one place this module could be destructive, and it is
        # not - the human must go through SS6's full attestation flow
        # (or direct hand-on-keyboard access) instead. This is not a
        # failure of the request; it is this page correctly declining
        # to make the risky choice on the operator's behalf.
        return RouteResult(
            "handed_off", 409,
            {"reason": reason, "target": target,
             "next_step": "use the full technical-eligibility gate (PRD SS6) "
                          "or direct console access to proceed"},
        )
    result = trigger.rebuild(target, config)
    if result.applied:
        return RouteResult("applied", 200, {"detail": result.detail})
    return RouteResult("refused", 422, {"detail": result.detail})


# ---------------------------------------------------------------------------
# Real HTTP wiring - thin; all decision logic lives in the handle_*
# functions above so it's testable without opening a real socket.
# ---------------------------------------------------------------------------

class SettingsHandler(http.server.BaseHTTPRequestHandler):
    """Serves both a real server-rendered HTML UI (browser form posts +
    a `session` cookie) and a JSON API (X-Session-Token header, used
    by tests and any future programmatic client) from the same routes,
    negotiated on the request's Content-Type."""

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html_response(self, status: int, body: bytes, set_cookie: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str, set_cookie: str | None = None) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _is_json_request(self) -> bool:
        return "application/json" in self.headers.get("Content-Type", "")

    def _read_body_bytes(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length) if length else b""

    def _read_json_body(self) -> dict:
        raw = self._read_body_bytes()
        try:
            return json.loads(raw.decode()) if raw else {}
        except ValueError:
            return {}

    def _read_form_body(self) -> dict:
        raw = self._read_body_bytes().decode()
        parsed = parse_qs(raw, keep_blank_values=True)
        return {k: v[0] for k, v in parsed.items()}

    def _cookie_token(self) -> str:
        raw = self.headers.get("Cookie", "")
        for part in raw.split(";"):
            part = part.strip()
            if part.startswith("session="):
                return part[len("session="):]
        return ""

    def _token(self) -> str:
        return self.headers.get("X-Session-Token", "") or self._cookie_token()

    def log_message(self, fmt, *args):  # noqa: A002 - stdlib signature
        pass  # quiet by default; caller can override via subclassing

    # -- POST -----------------------------------------------------------

    def do_POST(self):  # noqa: N802 - stdlib method name
        deps = self.server.deps  # type: ignore[attr-defined]
        now = deps["clock"]()
        json_mode = self._is_json_request()
        body = self._read_json_body() if json_mode else self._read_form_body()

        if self.path == "/login":
            result = handle_login(deps["verifier"], deps["sessions"],
                                   body.get("username", ""), body.get("password", ""), now)
            if json_mode:
                return self._json(result.status, {"outcome": result.outcome, **result.body})
            if result.outcome == "applied":
                return self._redirect("/settings", set_cookie=f"session={result.body['token']}; Path=/; HttpOnly")
            return self._html_response(result.status, render_login_page("Invalid username or password."))

        if self.path.startswith("/settings/"):
            section = self.path[len("/settings/"):]
            values = body if json_mode else self._parse_values_json(body)
            result = handle_settings_edit(deps["sessions"], deps["applier"],
                                           self._token(), section, values, now)
            if json_mode:
                return self._json(result.status, {"outcome": result.outcome, **result.body})
            if result.outcome == "refused" and result.status == 401:
                return self._redirect("/login")
            notice = result.body.get("detail") or result.body.get("reason", "")
            settings = deps["source"].current_settings()
            return self._html_response(result.status, render_settings_page(settings, notice))

        if self.path == "/setup/new-account":
            result = handle_new_account(deps["hasher"], body.get("username", ""), body.get("password", ""))
            if json_mode:
                return self._json(result.status, {"outcome": result.outcome, **result.body})
            if result.outcome == "applied":
                deps["store"].save_pending_account(body["username"], deps["hasher"](body["password"]))
                return self._html_response(200, render_setup_page("rebuild",
                    f"Account {body['username']!r} created. Now build the rebuild target."))
            return self._html_response(result.status, render_setup_page("account", "Username and password are both required."))

        if self.path == "/setup/rebuild":
            result = handle_rebuild(deps["eligibility"], deps["trigger"],
                                     body.get("target", ""), body.get("config", {}))
            if json_mode:
                return self._json(result.status, {"outcome": result.outcome, **result.body})
            notice = result.body.get("detail") or result.body.get("reason", "")
            return self._html_response(result.status, render_setup_page("rebuild", notice))

        result = RouteResult("handed_off", 404, {"reason": f"no route for {self.path!r}; no automatic action taken"})
        self._json(result.status, {"outcome": result.outcome, **result.body})

    def _parse_values_json(self, form_body: dict) -> dict:
        raw = form_body.get("values_json", "").strip()
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except ValueError:
            return {"_parse_error": raw}

    # -- GET ------------------------------------------------------------

    def do_GET(self):  # noqa: N802 - stdlib method name
        deps = self.server.deps  # type: ignore[attr-defined]
        now = deps["clock"]()
        json_mode = self._is_json_request() or "application/json" in self.headers.get("Accept", "")

        if self.path == "/" or self.path == "/login":
            if deps["sessions"].get(self._cookie_token(), now) is not None:
                return self._redirect("/settings")
            return self._html_response(200, render_login_page())

        if self.path == "/logout":
            return self._redirect("/login", set_cookie="session=; Path=/; Max-Age=0")

        if self.path == "/setup":
            return self._html_response(200, render_setup_page("account"))

        if self.path == "/settings":
            result = handle_settings_view(deps["sessions"], deps["source"], self._token(), now)
            if json_mode:
                return self._json(result.status, {"outcome": result.outcome, **result.body})
            if result.outcome != "applied":
                return self._redirect("/login")
            return self._html_response(200, render_settings_page(result.body["settings"]))

        result = RouteResult("handed_off", 404, {"reason": f"no route for {self.path!r}; no automatic action taken"})
        self._json(result.status, {"outcome": result.outcome, **result.body})


# ---------------------------------------------------------------------------
# Real default implementations - a genuinely working local deployment,
# not just the injectable interfaces above. Backed by one small JSON
# file so this runs standalone for evaluation without root, real
# hardware, or a real Proxmox install. Every "not yet wired to the
# real subsystem" spot below says so plainly in its returned detail
# text - functional today, honest about what it's actually doing.
# ---------------------------------------------------------------------------

class JsonFileStore:
    """One small on-disk JSON file backing users/settings/rebuild
    markers for a real, working local deployment. Not a database -
    this module's whole footprint is meant to stay this small."""

    def __init__(self, path: Path):
        self.path = path
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._write({
                "users": {
                    # DEV-ONLY seed account so this is usable the moment
                    # it's launched: username "root", password "baseline".
                    # A real deployment wires PasswordVerifier to the
                    # actual system account instead of this file.
                    "root": _sha512crypt("baseline", _new_salt()),
                },
                "settings": {
                    "network": {"hostname": "baseline", "dhcp": True},
                    "firewall": {"allow_lan_only": True},
                    "tether": {"enabled": False},
                    "ssh": {"password_auth": False},
                    "handoff": {"restored_categories": []},
                    "diagnostics": {
                        # Per decision record 22: all 5 install and run cleanly
                        # via apt on a real automated-install target. Fields
                        # below are what an operator actually needs to
                        # configure/select for each tool's *use*, not its
                        # install (install itself needs no fields - plain
                        # noninteractive apt-get). lm-sensors/nvme-cli need
                        # no fields at all - pure passive discovery.
                        "lm-sensors": {"install": "automatic", "fields": []},
                        "nvme-cli": {"install": "automatic", "fields": []},
                        "smartmontools": {
                            "install": "automatic",
                            "fields": [
                                {"name": "device", "type": "select", "source": "smartctl --scan-open",
                                 "label": "Device to inspect"},
                                {"name": "self_test_type", "type": "select", "options": ["short", "long"],
                                 "label": "Self-test type", "requires_explicit_confirm": True},
                            ],
                        },
                        "ethtool": {
                            "install": "automatic",
                            "fields": [
                                {"name": "interface", "type": "select", "source": "network.list_interfaces()",
                                 "label": "Interface to inspect"},
                            ],
                        },
                        "iperf3": {
                            "install": "automatic",
                            "fields": [
                                {"name": "role", "type": "select", "options": ["client", "server"],
                                 "label": "This host's role"},
                                {"name": "peer_address", "type": "text", "label": "Peer address"},
                                {"name": "port", "type": "number", "default": 5201, "label": "Port"},
                            ],
                            "requires_explicit_confirm": True,
                            "note": "Active network test with real side effects (PRD SS5.9a) - "
                                    "never auto-triggered, always operator-confirmed with both "
                                    "endpoints explicitly chosen.",
                        },
                        "tools_installed": [],
                    },
                },
                "pending_accounts": {},
                "rebuild_log": [],
            })

    def _read(self) -> dict:
        return json.loads(self.path.read_text())

    def _write(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=2))

    def get_user_hash(self, username: str) -> str | None:
        return self._read()["users"].get(username)

    def add_user(self, username: str, password_hash: str) -> None:
        data = self._read()
        data["users"][username] = password_hash
        self._write(data)

    def settings(self) -> dict:
        return self._read()["settings"]

    def update_section(self, section: str, values: dict) -> None:
        data = self._read()
        data["settings"].setdefault(section, {}).update(values)
        self._write(data)

    def save_pending_account(self, username: str, password_hash: str) -> None:
        data = self._read()
        data["pending_accounts"][username] = {"password_hash": password_hash, "config": {}}
        self._write(data)

    def record_rebuild(self, target: str, config: dict, now: float) -> None:
        data = self._read()
        data["rebuild_log"].append({"target": target, "config": config, "at": now})
        self._write(data)


class FileBackedPasswordVerifier(PasswordVerifier):
    def __init__(self, store: JsonFileStore):
        self.store = store

    def verify(self, username: str, password: str) -> bool:
        stored_hash = self.store.get_user_hash(username)
        if stored_hash is None:
            return False
        parts = stored_hash.split("$")
        if len(parts) < 4:
            return False
        salt = parts[2]
        return _sha512crypt(password, salt) == stored_hash


class FileBackedSettingsSource(SettingsSource):
    """Real settings where this process can genuinely read them
    (falls back cleanly per-item, matching hardware.py's own
    tolerance philosophy, rather than crashing the whole page)."""

    def __init__(self, store: JsonFileStore):
        self.store = store

    def current_settings(self) -> dict:
        settings = dict(self.store.settings())
        try:
            import network as _network  # local import: optional at runtime
            settings["_live_interfaces"] = _network.list_interfaces()
        except Exception as exc:  # pragma: no cover - environment dependent
            settings["_live_interfaces"] = {"available": False, "reason": str(exc)}
        return settings


class FileBackedSectionApplier(SectionApplier):
    """Persists the edit for real and says so plainly. Wiring this to
    the actual subsystem apply mechanisms (PRD SS5.10's firewall
    transaction, etc.) is future integration work, not pretended here."""

    def __init__(self, store: JsonFileStore):
        self.store = store

    def apply(self, section: str, new_values: dict) -> ApplyResult:
        self.store.update_section(section, new_values)
        return ApplyResult(
            applied=True,
            detail=f"{section} settings saved. Not yet wired to the live "
                   f"system's own apply mechanism for this section - saved "
                   f"here, real application is a follow-up integration.",
        )


class PathPrefixRebuildEligibility(RebuildEligibility):
    """Eligible only if the target path sits under one of the
    configured disposable-target prefixes - matches PRD SS4's
    image/virtual-disk-only boundary. Refuses everything else,
    including a bare device path like /dev/sdX, by construction."""

    def __init__(self, disposable_prefixes: tuple[str, ...] = ("/tmp/", "/var/tmp/")):
        self.disposable_prefixes = disposable_prefixes

    def is_eligible(self, target: str) -> tuple[bool, str]:
        if any(target.startswith(p) for p in self.disposable_prefixes):
            return True, f"{target} is under a configured disposable-target prefix"
        return False, (
            f"{target} is not under a configured disposable-target prefix "
            f"{self.disposable_prefixes} - PRD SS6's full technical-eligibility "
            f"gate is required for anything else, including any real device path"
        )


class LoggingRebuildTrigger(RebuildTrigger):
    """Records the rebuild request with a real, observable side
    effect (an on-disk log entry) rather than either pretending to
    reinstall anything or silently doing nothing. Actually reinstalling
    a target is drive_setup_install.py's job (already real-verified for
    image/virtual-disk targets in Gate C) - wiring that in is the next
    integration step, not duplicated here."""

    def __init__(self, store: JsonFileStore, clock=time.time):
        self.store = store
        self.clock = clock

    def rebuild(self, target: str, config: dict) -> ApplyResult:
        self.store.record_rebuild(target, config, self.clock())
        return ApplyResult(
            applied=True,
            detail=f"Rebuild request for {target} recorded. Not yet wired to "
                   f"drive_setup_install.py's real install pipeline - this "
                   f"proves the eligibility gate and trigger path work "
                   f"end-to-end; the actual reinstall call is a follow-up.",
        )


def default_hasher(password: str) -> str:
    return _sha512crypt(password, _new_salt())


# ---------------------------------------------------------------------------
# Minimal server-rendered HTML - no template engine dependency, matching
# this project's stdlib-only convention. Small enough to read end to end.
# ---------------------------------------------------------------------------

_PAGE_CSS = """
body { font-family: system-ui, sans-serif; max-width: 640px; margin: 3rem auto; padding: 0 1rem; color: #1a1a2e; }
h1 { font-size: 1.4rem; } h2 { font-size: 1.1rem; margin-top: 2rem; border-bottom: 1px solid #ddd; padding-bottom: .25rem; }
form { margin: .75rem 0; } label { display: block; margin: .5rem 0 .2rem; font-size: .9rem; }
input { padding: .4rem; width: 100%; max-width: 320px; box-sizing: border-box; }
button { margin-top: .75rem; padding: .5rem 1rem; background: #2a4d8f; color: white; border: none; border-radius: 4px; cursor: pointer; }
button.danger { background: #a63333; }
.notice { background: #fff6da; border: 1px solid #e0c568; padding: .6rem; border-radius: 4px; font-size: .9rem; }
.hint { color: #666; font-size: .82rem; }
pre { background: #f4f4f7; padding: .75rem; border-radius: 4px; overflow-x: auto; font-size: .85rem; }
a { color: #2a4d8f; }
"""


def _html(title: str, body: str) -> bytes:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>{title}</title><style>{_PAGE_CSS}</style></head>
<body><h1>Baseline settings</h1>{body}</body></html>""".encode()


def render_login_page(error: str = "") -> bytes:
    notice = f'<p class="notice">{error}</p>' if error else ""
    return _html("Log in", f"""
{notice}
<form method="post" action="/login">
  <label>Username <input name="username" value="root"></label>
  <label>Password <input name="password" type="password"></label>
  <button type="submit">Log in</button>
</form>
<p class="hint">Log in with your existing username and password to review
or change any current setting. Nothing here is reinstalled or wiped.</p>
<p><a href="/setup">Set up a new account and build a fresh configuration instead &raquo;</a></p>
""")


def render_settings_page(settings: dict, notice: str = "") -> bytes:
    rows = "".join(
        f"""<h2>{section}</h2>
<form method="post" action="/settings/{section}">
<pre>{json.dumps(values, indent=2)}</pre>
<label>New value (JSON object, merged into this section)
<input name="values_json" placeholder='{{"key": "value"}}'></label>
<button type="submit">Save {section}</button>
</form>"""
        for section, values in settings.items() if not section.startswith("_")
    )
    notice_html = f'<p class="notice">{notice}</p>' if notice else ""
    return _html("Settings", f"""
{notice_html}
<p>Every current setting is shown below. Change any section and save it -
only that section is re-applied, nothing else is touched.</p>
{rows}
<p><a href="/logout">Log out</a> &middot; <a href="/setup">Start a fresh setup instead &raquo;</a></p>
""")


def render_setup_page(step: str = "account", notice: str = "") -> bytes:
    notice_html = f'<p class="notice">{notice}</p>' if notice else ""
    if step == "account":
        body = """
<form method="post" action="/setup/new-account">
  <label>New username <input name="username"></label>
  <label>New password <input name="password" type="password"></label>
  <button type="submit">Create account</button>
</form>
<p class="hint">Building a fresh configuration under a new account never
touches your current running settings until you explicitly initiate a
rebuild from it, and that rebuild is only ever allowed against a
disposable target.</p>"""
    else:
        body = """
<form method="post" action="/setup/rebuild">
  <label>Rebuild target (disposable path)
  <input name="target" placeholder="/tmp/example-target.img"></label>
  <button type="submit" class="danger">Initiate rebuild</button>
</form>
<p class="hint">Only targets under a configured disposable prefix are
accepted here. Anything else is handed off rather than completed for you -
you'd need the full eligibility gate or direct console access.</p>"""
    return _html("New setup", f"{notice_html}{body}")


class SettingsWebServer:
    """LAN-scoped local HTTP server hosting the routes above. Not TLS
    here by default - matches PRD SS5.10's existing Proxmox-web-UI
    access model (LAN-scoped, not internet-exposed) rather than
    drive_setup_answer.py's fingerprint-pinned-HTTPS model, which
    exists there specifically to defend a one-time secret-bearing
    answer-file fetch, a different threat model than a login page an
    operator reaches from their own LAN."""

    def __init__(self, bind_host: str, bind_port: int, *, verifier: PasswordVerifier,
                 source: SettingsSource, applier: SectionApplier,
                 eligibility: RebuildEligibility, trigger: RebuildTrigger,
                 hasher, store=None, clock=time.time):
        self.deps = {
            "verifier": verifier, "source": source, "applier": applier,
            "eligibility": eligibility, "trigger": trigger, "hasher": hasher,
            "clock": clock, "sessions": SessionStore(), "store": store,
        }
        self.httpd = http.server.HTTPServer((bind_host, bind_port), SettingsHandler)
        self.httpd.deps = self.deps  # type: ignore[attr-defined]

    def serve_forever(self) -> None:
        self.httpd.serve_forever()

    def shutdown(self) -> None:
        self.httpd.shutdown()


def build_real_server(bind_host: str = "0.0.0.0", bind_port: int = 8100,
                       data_path: Path | None = None) -> SettingsWebServer:
    """A genuinely working, standalone deployment - one JSON file, no
    root, no real Proxmox install required. Default login is
    root/baseline (see JsonFileStore's seed) until PasswordVerifier is
    wired to the real system account."""
    store = JsonFileStore(data_path or Path("/tmp/baseline-settings-web/store.json"))
    return SettingsWebServer(
        bind_host, bind_port,
        verifier=FileBackedPasswordVerifier(store),
        source=FileBackedSettingsSource(store),
        applier=FileBackedSectionApplier(store),
        eligibility=PathPrefixRebuildEligibility(),
        trigger=LoggingRebuildTrigger(store),
        hasher=default_hasher,
        store=store,
    )


def resolve_data_path(env: dict) -> Path:
    """The real deployment's store must survive a reboot
    (`/var/lib/baseline`, matching every other persistent-state
    location this project uses) - the `/tmp` default in
    `build_real_server` exists only for standalone, no-install local
    evaluation and is deliberately kept as the fallback here so that
    use case is unaffected."""
    override = env.get("BASELINE_SETTINGS_WEB_DATA")
    if override:
        return Path(override)
    return Path("/tmp/baseline-settings-web/store.json")


def main() -> int:
    import os
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8100
    data_path = resolve_data_path(os.environ)
    server = build_real_server(bind_port=port, data_path=data_path)
    print(f"Baseline settings web UI on http://0.0.0.0:{port}/  (login: root / baseline)")
    print(f"Data store: {data_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
