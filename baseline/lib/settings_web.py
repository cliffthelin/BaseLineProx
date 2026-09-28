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
from urllib.parse import parse_qs, urlparse


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
    # Persona-aware wiring (work-queue item 25, decision record 78):
    # which persona was active (per persist_bind_mounts.get_active_persona)
    # at the moment this session was created. None when the caller
    # never supplied an ActivePersonaProvider - the pre-existing,
    # single-persona behavior, fully unaffected. This module's own
    # account/settings data lives under /var/lib/baseline, which
    # persist_bind_mounts.py bind-mounts onto whichever persona is
    # currently active - a session's data identity can change
    # underneath it if the active persona switches mid-session, so
    # this field lets that be caught rather than silently ignored.
    persona: str | None = None

    def expired(self, now: float) -> bool:
        return now > self.created + self.ttl_s


class ActivePersonaProvider:
    """Answers which persona is currently active. The real
    implementation calls `persist_bind_mounts.get_active_persona`
    against a real Runner; injectable so tests never need a real
    filesystem, matching this module's own established pattern for
    every other boundary (`PasswordVerifier`, `SettingsSource`, ...).
    Entirely optional - a caller that never passes one to
    `handle_login`/`handle_settings_view`/`handle_settings_edit` gets
    the pre-existing, persona-unaware behavior unchanged."""

    def current_persona(self) -> str:
        raise NotImplementedError


@dataclass
class SessionStore:
    sessions: dict = field(default_factory=dict)

    def create(self, username: str, now: float, persona: str | None = None) -> LoginSession:
        token = secrets.token_urlsafe(32)
        session = LoginSession(token=token, username=username, created=now, persona=persona)
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
                  username: str, password: str, now: float,
                  persona_provider: ActivePersonaProvider | None = None) -> RouteResult:
    if verifier.verify(username, password):
        persona = persona_provider.current_persona() if persona_provider is not None else None
        session = sessions.create(username, now, persona=persona)
        return RouteResult("applied", 200, {"token": session.token})
    # Deliberately identical response shape/timing-irrelevant message
    # for "no such user" and "wrong password" - no username enumeration.
    return RouteResult("refused", 401, {"error": "invalid credentials"})


def _stale_persona_result(session: LoginSession, persona_provider: ActivePersonaProvider | None) -> RouteResult | None:
    """Returns a refusal RouteResult if the active persona has changed
    since this session was created, else None. A no-op (returns None
    unconditionally) when either the caller never supplied a
    provider, or the session itself never recorded a persona (both mean
    "not opted into persona-awareness") - the pre-existing behavior."""
    if persona_provider is None or session.persona is None:
        return None
    current = persona_provider.current_persona()
    if current != session.persona:
        return RouteResult(
            "refused", 401,
            {"error": "stale session - the active persona changed since login; log in again",
             "session_persona": session.persona, "active_persona": current})
    return None


def handle_settings_view(sessions: SessionStore, source: SettingsSource,
                          token: str, now: float,
                          persona_provider: ActivePersonaProvider | None = None) -> RouteResult:
    session = sessions.get(token, now)
    if session is None:
        return RouteResult("refused", 401, {"error": "not authenticated"})
    stale = _stale_persona_result(session, persona_provider)
    if stale is not None:
        return stale
    return RouteResult("applied", 200, {"settings": source.current_settings()})


def handle_settings_edit(sessions: SessionStore, applier: SectionApplier,
                          token: str, section: str, new_values: dict,
                          now: float, persona_provider: ActivePersonaProvider | None = None) -> RouteResult:
    session = sessions.get(token, now)
    if session is None:
        return RouteResult("refused", 401, {"error": "not authenticated"})
    stale = _stale_persona_result(session, persona_provider)
    if stale is not None:
        return stale
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


# ---------------------------------------------------------------------------
# The Admin tab (work-queue item 28, decision record 80): a real web
# surface over settings_store.py's schema-driven groups (session TTLs,
# auto-start persona, per-volume mode, and whatever else the schema
# grows to hold - "potentially hundreds of settings," per direct
# instruction). Deliberately separate from handle_settings_view/_edit's
# own flat KNOWN_SECTIONS model above (network/firewall/...), which
# predates settings_store.py and stays scoped to that older
# subsystem-config surface - the two are different stores with
# different data, not two ways to reach the same one.
#
# Editing an Admin setting requires a real, currently-elevated
# admin_elevation ticket, not just a valid login session - these
# settings are cross-persona-consequential (auto-start-persona, session
# TTLs affecting every persona, per-volume mode) matching admin's own
# "essentially sudo or root" design (decision record 76). Viewing is
# allowed on a valid session alone, matching every other settings page.
# ---------------------------------------------------------------------------

def handle_admin_view(sessions: SessionStore, runner, token: str, now: float) -> RouteResult:
    session = sessions.get(token, now)
    if session is None:
        return RouteResult("refused", 401, {"error": "not authenticated"})
    if runner is None:
        return RouteResult(
            "handed_off", 409,
            {"reason": "no Runner configured for this deployment - the Admin tab needs one to "
                        "reach settings_store.py's real storage on BASELINE"})
    import settings_store
    return RouteResult("applied", 200, {"settings": settings_store.all_effective_settings(runner)})


def handle_admin_elevate(elevation_store, verify_fn, sessions: SessionStore, token: str,
                          passphrase: str, now: float) -> RouteResult:
    session = sessions.get(token, now)
    if session is None:
        return RouteResult("refused", 401, {"error": "not authenticated"})
    if verify_fn is None:
        return RouteResult(
            "handed_off", 409,
            {"reason": "no elevation verifier configured for this deployment"})
    import admin_elevation
    if admin_elevation.attempt_elevation(elevation_store, verify_fn, passphrase, now):
        return RouteResult("applied", 200, {"detail": "elevated"})
    return RouteResult("refused", 401, {"error": "invalid elevation passphrase"})


def handle_admin_edit(sessions: SessionStore, runner, elevation_store, token: str,
                       group: str, key: str, value, now: float) -> RouteResult:
    session = sessions.get(token, now)
    if session is None:
        return RouteResult("refused", 401, {"error": "not authenticated"})
    if runner is None:
        return RouteResult(
            "handed_off", 409,
            {"reason": "no Runner configured for this deployment - the Admin tab needs one to "
                        "reach settings_store.py's real storage on BASELINE"})
    import admin_elevation
    if not admin_elevation.require_elevation(elevation_store, runner, now):
        return RouteResult(
            "refused", 403,
            {"error": "admin elevation required - enter the elevation passphrase first"})
    import settings_store
    try:
        settings_store.set_setting(runner, group, key, value)
    except KeyError as exc:
        return RouteResult("handed_off", 409, {"reason": str(exc)})
    return RouteResult("applied", 200, {"detail": f"{group}.{key} set to {value!r}"})


# ---------------------------------------------------------------------------
# Recovery mode's userless discovery view (work-queue item 26, decision
# record 81). Deliberately no `sessions`/`token` parameter anywhere in
# this section - guest-tier by construction, matching
# `recovery_tiers.GUEST_ACTIONS`' `view_recovery_screen` being always
# present, never conditionally withheld. `runner=None` hands off rather
# than crashing, same convention as the Admin tab above.
# ---------------------------------------------------------------------------

def handle_recovery_view(runner, *, personas: tuple) -> RouteResult:
    if runner is None:
        return RouteResult(
            "handed_off", 409,
            {"reason": "no Runner configured for this deployment - recovery discovery needs one"})
    import recovery_mode
    report = recovery_mode.discover(runner, personas=personas)
    return RouteResult("applied", 200, {
        "personas_found": report.personas_found,
        "personas_missing": report.personas_missing,
        "active_persona": report.active_persona,
        "recovery_active": recovery_mode.is_active(runner),
    })


def handle_recovery_exit(runner, *, personas: tuple, now: float) -> RouteResult:
    if runner is None:
        return RouteResult(
            "handed_off", 409,
            {"reason": "no Runner configured for this deployment - recovery exit needs one"})
    import recovery_mode
    result = recovery_mode.attempt_exit(runner, personas=personas, now=now)
    if not result.applied:
        return RouteResult("refused", 409, {"reason": result.detail})
    return RouteResult("applied", 200, {"detail": result.detail})


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
                                   body.get("username", ""), body.get("password", ""), now,
                                   persona_provider=deps.get("persona_provider"))
            if json_mode:
                return self._json(result.status, {"outcome": result.outcome, **result.body})
            if result.outcome == "applied":
                return self._redirect("/settings", set_cookie=f"session={result.body['token']}; Path=/; HttpOnly")
            return self._html_response(result.status, render_login_page("Invalid username or password."))

        if self.path.startswith("/settings/"):
            section = self.path[len("/settings/"):]
            if json_mode:
                values = body
            else:
                current = deps["source"].current_settings().get(section, {})
                values = reconstruct_typed_form_values(body, list(current.keys()))
            result = handle_settings_edit(deps["sessions"], deps["applier"],
                                           self._token(), section, values, now,
                                           persona_provider=deps.get("persona_provider"))
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

        if self.path == "/recovery/exit":
            result = handle_recovery_exit(deps.get("runner"), personas=deps.get("personas", ()), now=now)
            if json_mode:
                return self._json(result.status, {"outcome": result.outcome, **result.body})
            notice = result.body.get("detail") or result.body.get("reason", "")
            return self._redirect(f"/recovery?notice={notice}")

        if self.path == "/admin/elevate":
            result = handle_admin_elevate(deps["elevation_store"], deps.get("elevation_verify_fn"),
                                           deps["sessions"], self._token(), body.get("passphrase", ""), now)
            if json_mode:
                return self._json(result.status, {"outcome": result.outcome, **result.body})
            if result.outcome == "refused" and result.status == 401 and \
                    result.body.get("error") != "invalid elevation passphrase":
                return self._redirect("/login")
            notice = result.body.get("detail") or result.body.get("error") or result.body.get("reason", "")
            return self._redirect(f"/admin?notice={notice}")

        if self.path.startswith("/admin/settings/"):
            rest = self.path[len("/admin/settings/"):]
            group, _, key = rest.partition("/")
            values = body if json_mode else reconstruct_typed_form_values(body, ["value"])
            result = handle_admin_edit(deps["sessions"], deps.get("runner"), deps["elevation_store"],
                                        self._token(), group, key, values.get("value"), now)
            if json_mode:
                return self._json(result.status, {"outcome": result.outcome, **result.body})
            if result.outcome == "refused" and result.status == 401:
                return self._redirect("/login")
            notice = result.body.get("detail") or result.body.get("error") or result.body.get("reason", "")
            return self._redirect(f"/admin?notice={notice}")

        result = RouteResult("handed_off", 404, {"reason": f"no route for {self.path!r}; no automatic action taken"})
        self._json(result.status, {"outcome": result.outcome, **result.body})

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
            result = handle_settings_view(deps["sessions"], deps["source"], self._token(), now,
                                           persona_provider=deps.get("persona_provider"))
            if json_mode:
                return self._json(result.status, {"outcome": result.outcome, **result.body})
            if result.outcome != "applied":
                return self._redirect("/login")
            return self._html_response(200, render_settings_page(result.body["settings"]))

        if self.path.startswith("/recovery"):
            result = handle_recovery_view(deps.get("runner"), personas=deps.get("personas", ()))
            if json_mode:
                return self._json(result.status, {"outcome": result.outcome, **result.body})
            if result.outcome != "applied":
                return self._html_response(result.status, render_recovery_page({}, result.body.get("reason", "")))
            return self._html_response(200, render_recovery_page(result.body))

        if self.path.startswith("/admin"):
            result = handle_admin_view(deps["sessions"], deps.get("runner"), self._token(), now)
            if json_mode:
                return self._json(result.status, {"outcome": result.outcome, **result.body})
            if result.outcome == "refused" and result.status == 401:
                return self._redirect("/login")
            if result.outcome != "applied":
                return self._html_response(result.status, render_admin_page({}, result.body.get("reason", "")))
            notice = parse_qs(urlparse(self.path).query).get("notice", [""])[0]
            elevated = deps["elevation_store"].is_elevated(deps.get("runner"), now) if deps.get("runner") else False
            return self._html_response(200, render_admin_page(result.body["settings"], notice, elevated=elevated))

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
                # DEV-ONLY seed elevation passphrase (work-queue item
                # 28): "baseline-admin" - deliberately different from
                # the login password above, matching decision record
                # 76's "a SEPARATE, additional passphrase - not the
                # same secret as admin's own base login."
                "elevation_password_hash": _sha512crypt("baseline-admin", _new_salt()),
            })

    def _read(self) -> dict:
        return json.loads(self.path.read_text())

    def _write(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=2))

    def get_user_hash(self, username: str) -> str | None:
        return self._read()["users"].get(username)

    def get_elevation_hash(self) -> str | None:
        return self._read().get("elevation_password_hash")

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


class SystemPasswordVerifier(PasswordVerifier):
    """The real implementation `PasswordVerifier`'s own docstring
    described as deliberately unbuilt: verifies against the machine's
    actual `/etc/shadow` account - needs root, which
    `baseline-settings-web.service`/`baseline.service` already run as
    (no `User=` override in either unit). "Standard Ubuntu design" in
    the sense that matters here: this proves the human at the browser
    genuinely knows the real admin's password, right now, for this
    specific change - not a re-derivation of privilege the process
    already has as root.

    Reads `/etc/shadow` directly rather than via the stdlib `spwd`
    module - `spwd` was removed in Python 3.13, the same real
    constraint this file's own `_sha512crypt` docstring already
    documents for the `crypt` module. Reuses `_sha512crypt` itself
    directly - the exact same technique
    `FileBackedPasswordVerifier`/`FileBackedElevationVerifier` already
    use, just against the real shadow hash instead of a JsonFileStore
    one. Every real Debian/Proxmox account's hash is `$6$...` (SHA-512
    crypt) by default - a different scheme (e.g. `$y$` yescrypt) is
    refused cleanly (`False`), never crashes."""

    def __init__(self, shadow_path: str = "/etc/shadow", read_text=None):
        self.shadow_path = shadow_path
        self._read_text = read_text or (lambda path: Path(path).read_text())

    def _stored_hash(self, username: str) -> str | None:
        try:
            content = self._read_text(self.shadow_path)
        except (OSError, PermissionError):
            return None
        for line in content.splitlines():
            fields = line.split(":")
            if len(fields) >= 2 and fields[0] == username:
                return fields[1]
        return None

    def verify(self, username: str, password: str) -> bool:
        stored_hash = self._stored_hash(username)
        if not stored_hash:
            return False
        parts = stored_hash.split("$")
        if len(parts) < 4 or parts[1] != "6":
            return False
        salt = parts[2]
        return _sha512crypt(password, salt) == stored_hash


class SystemElevationVerifier:
    """Adapts `SystemPasswordVerifier`'s `.verify(username, password)`
    (the `PasswordVerifier` login contract, two arguments) to the
    single-argument `verify_fn(password) -> bool` shape
    `admin_elevation.attempt_elevation` and the Drive Administration
    action route both actually call. Bound to one real, fixed
    `username` at construction - real elevation checks the *specific*
    admin account's own password, not an ambient/unspecified one.
    Found missing (`SystemPasswordVerifier` used directly as
    `elevation_verify_fn` would raise `TypeError` - it defines no
    `__call__`) by direct question, before it ever ran for real."""

    def __init__(self, username: str, verifier: "SystemPasswordVerifier | None" = None):
        self.username = username
        self.verifier = verifier or SystemPasswordVerifier()

    def __call__(self, password: str) -> bool:
        return self.verifier.verify(self.username, password)


class FileBackedElevationVerifier:
    """`admin_elevation.attempt_elevation`'s own "verify_fn as a plain
    callable" convention - a real default backed by the same
    JsonFileStore, but under its own separate hash field, never the
    login password's."""

    def __init__(self, store: JsonFileStore):
        self.store = store

    def __call__(self, passphrase: str) -> bool:
        stored_hash = self.store.get_elevation_hash()
        if stored_hash is None:
            return False
        parts = stored_hash.split("$")
        if len(parts) < 4:
            return False
        salt = parts[2]
        return _sha512crypt(passphrase, salt) == stored_hash


class RunnerBackedActivePersonaProvider(ActivePersonaProvider):
    """The real `ActivePersonaProvider`: reuses
    `persist_bind_mounts.get_active_persona` against a real Runner,
    directly - never re-derives the active-persona marker logic here."""

    def __init__(self, runner):
        self.runner = runner

    def current_persona(self) -> str:
        import persist_bind_mounts as pbm
        return pbm.get_active_persona(self.runner)


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
:root { color-scheme: dark; }
html, body { background: #0d0e13; }
body { font-family: -apple-system, system-ui, "Segoe UI", sans-serif; max-width: 640px; margin: 3rem auto; padding: 0 1rem; color: #e7e9f0; }
h1 { font-size: 1.4rem; color: #f2f3f8; } h2 { font-size: 1.1rem; margin-top: 2rem; color: #ccd0e0; border-bottom: 1px solid #262838; padding-bottom: .25rem; }
form { margin: .75rem 0; } label { display: block; margin: .5rem 0 .2rem; font-size: .9rem; color: #9aa0ba; }
input { padding: .5rem .6rem; width: 100%; max-width: 320px; box-sizing: border-box; color: #e7e9f0; background: #171923; border: 1px solid #33364a; border-radius: 6px; }
input::placeholder { color: #5c6180; }
button { margin-top: .75rem; padding: .5rem 1rem; background: #3f63b8; color: #f2f3f8; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; }
button:hover { background: #4a72cf; }
button.danger { background: #b6414a; }
button.danger:hover { background: #cc4b55; }
.notice { background: #1a2233; border: 1px solid #2f4573; padding: .6rem .9rem; border-radius: 8px; font-size: .9rem; color: #cfe0ff; }
.hint { color: #8890a6; font-size: .82rem; }
pre { background: #171923; border: 1px solid #262838; color: #ccd0e0; padding: .75rem; border-radius: 6px; overflow-x: auto; font-size: .85rem; }
a { color: #7fa4ec; }
a:visited { color: #a48ce0; }
table { border-collapse: collapse; width: 100%; margin: .5rem 0 1.5rem; }
th, td { text-align: left; padding: .4rem .6rem; border-bottom: 1px solid #21232f; font-size: .9rem; color: #ccd0e0; }
th { color: #8890a6; font-weight: 600; font-size: .8rem; text-transform: uppercase; letter-spacing: .04em; }
.baseline-nav { display: flex; gap: 1.25rem; padding: .75rem 0 1rem; margin-bottom: 1rem; border-bottom: 2px solid #262838; font-size: .95rem; }
.baseline-nav a { color: #9aa0ba; text-decoration: none; padding: .25rem .1rem; }
.baseline-nav a.active { color: #f2f3f8; font-weight: 700; border-bottom: 2px solid #5b7fd4; }
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


def render_field_input(name: str, value, *, options: list | None = None) -> str:
    """A real, typed HTML control for one settings value - a checkbox
    for a real boolean, a number field for a real number, a dropdown
    for a known string enum (`options`), plain text otherwise - never
    a JSON text box for an ordinary scalar. Only a genuinely nested
    value (list/dict) falls back to a labeled, clearly-advanced raw
    JSON textarea, since that's real structured data no simple control
    could represent anyway.

    Emits a hidden `<name>__type` field alongside the control so the
    server can reconstruct the real Python type from the submitted
    form without re-querying the current stored value - self-
    describing, one shared parser (`reconstruct_typed_form_values`)
    for every settings form on this app."""
    type_name = ("bool" if isinstance(value, bool) else
                 "int" if isinstance(value, int) else
                 "float" if isinstance(value, float) else
                 "str" if isinstance(value, str) else "json")
    hidden = f'<input type="hidden" name="{name}__type" value="{type_name}">'
    if type_name == "bool":
        checked = "checked" if value else ""
        return hidden + f'<input type="checkbox" name="{name}" value="true" {checked}>'
    if options is not None:
        opts = "".join(f'<option value="{o}" {"selected" if o == value else ""}>{o}</option>' for o in options)
        return hidden + f'<select name="{name}">{opts}</select>'
    if type_name in ("int", "float"):
        step = "1" if type_name == "int" else "any"
        return hidden + f'<input type="number" name="{name}" value="{value}" step="{step}">'
    if type_name == "str":
        return hidden + f'<input type="text" name="{name}" value="{value}">'
    return hidden + f'<textarea name="{name}" rows="3">{json.dumps(value, indent=2)}</textarea>'


def reconstruct_typed_form_values(form_body: dict, field_names: list) -> dict:
    """The other half of `render_field_input`: rebuilds real Python-
    typed values from a submitted HTML form using each field's own
    `<name>__type` hidden hint. Checkboxes only appear in the
    submitted body at all when checked (standard HTML form behavior),
    so presence/absence alone tells us True/False - no hidden
    always-present fallback field needed for booleans specifically."""
    result = {}
    for name in field_names:
        type_name = form_body.get(f"{name}__type", "str")
        if type_name == "bool":
            result[name] = name in form_body
            continue
        raw = form_body.get(name)
        if raw is None or raw == "":
            continue
        if type_name == "int":
            try:
                result[name] = int(raw)
            except ValueError:
                pass
        elif type_name == "float":
            try:
                result[name] = float(raw)
            except ValueError:
                pass
        elif type_name == "json":
            try:
                result[name] = json.loads(raw)
            except ValueError:
                pass
        else:
            result[name] = raw
    return result


def render_settings_page(settings: dict, notice: str = "") -> bytes:
    rows = "".join(
        f"""<h2>{section}</h2>
<form method="post" action="/settings/{section}">
{"".join(f'<label>{key} {render_field_input(key, value)}</label>' for key, value in values.items())}
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


def render_recovery_page(discovery: dict, notice: str = "") -> bytes:
    """The userless discovery view (work-queue item 26) - no login
    form anywhere on this page, matching guest-tier access being
    always present. `discovery` is `handle_recovery_view`'s own body
    dict; an empty dict (the hand-off case) renders a plain notice."""
    notice_html = f'<p class="notice">{notice}</p>' if notice else ""
    if not discovery:
        return _html("Recovery", f"{notice_html}<p>Recovery discovery is not available on this deployment.</p>")
    found = ", ".join(discovery.get("personas_found") or []) or "none"
    missing = ", ".join(discovery.get("personas_missing") or []) or "none"
    active = discovery.get("active_persona") or "none"
    recovery_active = discovery.get("recovery_active")
    # The exit control only makes sense to show while recovery mode is
    # genuinely active - showing "leave recovery mode" when it isn't
    # implies there's something to leave, which there isn't.
    if recovery_active:
        status = "Recovery mode is currently ACTIVE."
        exit_html = """<form method="post" action="/recovery/exit">
  <button type="submit">Attempt to leave recovery mode</button>
</form>
<p class="hint">Leaving is refused until at least one persona volume is
confirmed mounted read-write - this page cannot bypass that.</p>"""
    else:
        status = "Recovery mode is not active - nothing to leave."
        exit_html = ""
    return _html("Recovery", f"""
{notice_html}
<p>{status}</p>
<p>Personas with a real, currently-mounted persistence volume: {found}</p>
<p>Personas missing a volume: {missing}</p>
<p>Currently active persona: {active}</p>
{exit_html}
""")


def render_admin_page(settings: dict, notice: str = "", elevated: bool = False) -> bytes:
    """The Admin tab (work-queue item 28): every settings_store.py
    group as its own sub-tab section. Editing a value is refused
    server-side without a real elevation ticket regardless of what
    this page renders - the elevation form below is a convenience, not
    the enforcement point."""
    elevate_html = "" if elevated else """
<form method="post" action="/admin/elevate">
  <label>Admin elevation passphrase <input name="passphrase" type="password"></label>
  <button type="submit">Elevate</button>
</form>
<p class="hint">Required before any Admin setting below can be changed - a separate
passphrase from your login, matching real sudo's own short-lived cache.</p>"""
    import settings_store
    schema_options = {(s.group, s.key): s.options for s in settings_store.SCHEMA}
    sections = "".join(
        f"""<h2>{group}</h2>""" + "".join(
            f"""<form method="post" action="/admin/settings/{group}/{key}">
<label>{key} {render_field_input("value", value, options=schema_options.get((group, key)))}</label>
<button type="submit" {"disabled" if not elevated else ""}>Save</button>
</form>"""
            for key, value in values.items()
        )
        for group, values in settings.items()
    )
    notice_html = f'<p class="notice">{notice}</p>' if notice else ""
    return _html("Admin", f"""
{notice_html}
{elevate_html}
<p>Every current Admin setting is shown below, grouped by sub-tab. Changing one
requires elevation (above) first - matching admin's own "sudo or root" design.</p>
{sections}
<p><a href="/settings">Back to Settings</a> &middot; <a href="/logout">Log out</a></p>
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
                 hasher, store=None, clock=time.time,
                 persona_provider: ActivePersonaProvider | None = None,
                 runner=None, elevation_verify_fn=None, personas: tuple | None = None):
        import admin_elevation
        if personas is None:
            import drive_installer
            personas = drive_installer.DEFAULT_PERSONAS
        self.deps = {
            "verifier": verifier, "source": source, "applier": applier,
            "eligibility": eligibility, "trigger": trigger, "hasher": hasher,
            "clock": clock, "sessions": SessionStore(), "store": store,
            "persona_provider": persona_provider,
            "runner": runner, "elevation_store": admin_elevation.ElevationStore(),
            "elevation_verify_fn": elevation_verify_fn, "personas": personas,
        }
        self.httpd = http.server.HTTPServer((bind_host, bind_port), SettingsHandler)
        self.httpd.deps = self.deps  # type: ignore[attr-defined]

    def serve_forever(self) -> None:
        self.httpd.serve_forever()

    def shutdown(self) -> None:
        self.httpd.shutdown()


def build_real_server(bind_host: str = "0.0.0.0", bind_port: int = 8100,
                       data_path: Path | None = None, runner=None) -> SettingsWebServer:
    """A genuinely working, standalone deployment - one JSON file, no
    root, no real Proxmox install required. Default login is
    root/baseline (see JsonFileStore's seed) until PasswordVerifier is
    wired to the real system account.

    `runner` (optional, real-deployment only) wires a real
    `RunnerBackedActivePersonaProvider` so a session becomes stale if
    the active persona switches underneath it (decision record 78) -
    omitted (the default) keeps this fully usable standalone with no
    Runner/persistence layer available at all, matching this
    function's own "no root, no real hardware required" design."""
    store = JsonFileStore(data_path or Path("/tmp/baseline-settings-web/store.json"))
    persona_provider = RunnerBackedActivePersonaProvider(runner) if runner is not None else None
    return SettingsWebServer(
        bind_host, bind_port,
        verifier=FileBackedPasswordVerifier(store),
        source=FileBackedSettingsSource(store),
        applier=FileBackedSectionApplier(store),
        eligibility=PathPrefixRebuildEligibility(),
        trigger=LoggingRebuildTrigger(store),
        hasher=default_hasher,
        store=store,
        persona_provider=persona_provider,
        runner=runner,
        elevation_verify_fn=FileBackedElevationVerifier(store),
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
    from repair import RealRunner
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8100
    data_path = resolve_data_path(os.environ)
    server = build_real_server(bind_port=port, data_path=data_path, runner=RealRunner())
    print(f"Baseline settings web UI on http://0.0.0.0:{port}/  (login: root / baseline)")
    print(f"Data store: {data_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
