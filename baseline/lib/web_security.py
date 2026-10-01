"""Web hardening shared by both web apps (baseline_web.py and the standalone settings_web.py).

- Security headers on EVERY response: a content security policy (no framing, forms post only to
  ourselves, no <base>), no MIME sniffing, no caching of what are often sensitive pages, no referrer.
- The session cookie is HttpOnly and SameSite=Strict, so a browser does not send it on a request that a
  page on another site triggers.
- A POST must come from this site: its Origin (or Referer) has to match the Host. A POST that carries a
  session cookie and neither header is refused (browsers always send Origin on a POST). Scripts and curl
  that send no cookie are unaffected.
- Every endpoint that checks a password (login, recovery unlock, admin elevation) is rate limited per
  client address, with a global ceiling against floods from many addresses. The lockout is TEMPORARY and
  capped (it never reaches 15 minutes by much, and it expires by itself), and it applies only to the web
  app: the machine's own console is unaffected, so this can slow a guesser but cannot lock the owner out
  for good. While a client is locked even the right password is refused, so a lockout is not an oracle.
"""
from __future__ import annotations

import math
import threading
from urllib.parse import urlparse

SESSION_COOKIE_ATTRS = "Path=/; HttpOnly; SameSite=Strict"

# 'unsafe-inline' stays for script and style because the pages carry their own small inline script and CSS;
# everything else is closed: nothing external, no framing, no <base>, forms post only to this origin.
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
)
SECURITY_HEADERS = (
    ("Content-Security-Policy", CONTENT_SECURITY_POLICY),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
)


def session_cookie(token: str) -> str:
    return f"session={token}; {SESSION_COOKIE_ATTRS}"


def clear_session_cookie() -> str:
    return f"session=; Max-Age=0; {SESSION_COOKIE_ATTRS}"


def _same_host(url: str, host: str | None) -> bool:
    if not host:
        return False
    try:
        return urlparse(url).netloc.lower() == host.lower()
    except ValueError:
        return False


def origin_ok(headers, *, has_cookie: bool) -> bool:
    """Is this POST from this site? `headers` is a mapping (a dict, or the handler's `self.headers`)."""
    lowered = {str(k).lower(): v for k, v in headers.items()}
    origin, referer, host = lowered.get("origin"), lowered.get("referer"), lowered.get("host")
    if origin is not None:
        return origin != "null" and _same_host(origin, host)
    if referer:
        return _same_host(referer, host)
    return not has_cookie


class AttemptLimiter:
    """Counts failed password checks and imposes short, escalating, capped lockouts. In memory: it resets when
    the service restarts, which is acceptable because the lockout is only a speed bump against guessing."""

    def __init__(self, *, max_failures: int = 5, window_s: float = 900, base_lock_s: float = 30,
                 max_lock_s: float = 900, global_max_failures: int = 60, global_window_s: float = 3600,
                 global_lock_s: float = 300, max_tracked: int = 10000):
        self.max_failures, self.window_s = max_failures, window_s
        self.base_lock_s, self.max_lock_s = base_lock_s, max_lock_s
        self.global_max_failures, self.global_window_s, self.global_lock_s = (
            global_max_failures, global_window_s, global_lock_s)
        self.max_tracked = max_tracked
        self._by_key: dict = {}
        self._global: dict = {}
        self._lock = threading.Lock()

    def check(self, scope: str, client: str, now: float) -> int:
        """Seconds the client must wait (0 if it may try)."""
        with self._lock:
            per = self._by_key.get((scope, client))
            glob = self._global.get(scope)
            wait = max(per["lock_until"] if per else 0, glob["lock_until"] if glob else 0) - now
            return math.ceil(wait) if wait > 0 else 0

    def failure(self, scope: str, client: str, now: float) -> None:
        with self._lock:
            per = self._by_key.setdefault((scope, client), {"fails": [], "lock_until": 0.0, "strikes": 0, "seen": now})
            per["seen"] = now
            per["fails"] = [t for t in per["fails"] if t > now - self.window_s] + [now]
            if len(per["fails"]) >= self.max_failures:
                per["strikes"] += 1
                per["lock_until"] = now + min(self.base_lock_s * 2 ** (per["strikes"] - 1), self.max_lock_s)
                per["fails"] = []
            glob = self._global.setdefault(scope, {"fails": [], "lock_until": 0.0})
            glob["fails"] = [t for t in glob["fails"] if t > now - self.global_window_s] + [now]
            if len(glob["fails"]) >= self.global_max_failures:
                glob["lock_until"] = now + self.global_lock_s
                glob["fails"] = []
            if len(self._by_key) > self.max_tracked:
                self._prune(now)

    def success(self, scope: str, client: str, now: float) -> None:
        with self._lock:
            self._by_key.pop((scope, client), None)

    def tracked(self) -> int:
        with self._lock:
            return len(self._by_key)

    def _prune(self, now: float) -> None:
        """Drop clients with no active lockout and no recent failures, then the least recently seen."""
        stale = [k for k, v in self._by_key.items()
                 if v["lock_until"] <= now and (not v["fails"] or v["fails"][-1] <= now - self.window_s)]
        for key in stale:
            self._by_key.pop(key, None)
        if len(self._by_key) > self.max_tracked:
            for key in sorted(self._by_key, key=lambda k: self._by_key[k]["seen"])[: len(self._by_key) - self.max_tracked]:
                self._by_key.pop(key, None)


def get_limiter(deps: dict) -> AttemptLimiter:
    limiter = deps.get("limiter")
    if limiter is None:
        limiter = deps["limiter"] = AttemptLimiter()
    return limiter


class SecureHandlerMixin:
    """Put first in a handler's bases: adds the security headers to every response and offers `_reject`."""

    def end_headers(self):  # noqa: D401 - stdlib hook
        for name, value in SECURITY_HEADERS:
            self.send_header(name, value)
        super().end_headers()

    def _reject(self, status: int, message: str, retry_after: int | None = None) -> None:
        body = (message + "\n").encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if retry_after is not None:
            self.send_header("Retry-After", str(retry_after))
        self.end_headers()
        self.wfile.write(body)

    def _client_address(self) -> str:
        return self.client_address[0]

    def _throttled(self, scope: str, now: float) -> bool:
        """True (after answering 429) if this client must wait before another password attempt."""
        wait = get_limiter(self.server.deps).check(scope, self._client_address(), now)  # type: ignore[attr-defined]
        if wait:
            self._reject(429, f"Too many attempts. Try again in {wait} seconds.", retry_after=wait)
            return True
        return False

    def _record_attempt(self, scope: str, now: float, *, ok: bool) -> None:
        limiter = get_limiter(self.server.deps)  # type: ignore[attr-defined]
        if ok:
            limiter.success(scope, self._client_address(), now)
        else:
            limiter.failure(scope, self._client_address(), now)
