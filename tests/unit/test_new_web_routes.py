"""The routes added 2026-10-13, driven through the real HTTP server with a real session: vault paste, the guided Claude sign-in (a real
child process standing in for the CLI), Network, Sensors, Chat, Tools and the console switch. Nothing is stubbed at the HTTP layer."""
import http.client
import sys
import time
import urllib.parse

import pytest

import vault as v
from test_baseline_web import _RealServerCase, _base_deps

SECRET = "sk-test-secret-value-" + "A1b2" * 6
CLI = r'''
import sys
print("https://claude.com/cai/oauth/authorize?code=true&state=s1", flush=True)
code = sys.stdin.readline().strip()
if code == "right-code-777":
    print("sk-ant-oat01-" + "Zq4" * 24, flush=True)
else:
    sys.exit(2)
'''


def req(case, method, path, fields=None, cookie=True):
    conn = http.client.HTTPConnection("127.0.0.1", case.port, timeout=10)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if cookie:
        headers["Cookie"] = f"session={case.token}"
    body = urllib.parse.urlencode(fields or {}).encode() if method == "POST" else None
    if method == "POST":
        headers["Origin"] = f"http://127.0.0.1:{case.port}"
    conn.request(method, path, body=body, headers=headers)
    r = conn.getresponse()
    data = r.read()
    out = (r.status, r.getheader("Location"), data.decode("utf8", "replace"))
    conn.close()
    return out


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "ADMIN_VAULT", str(tmp_path / "admin-vault"))
    monkeypatch.setattr(v, "PERSONAL_VAULT", str(tmp_path / "personal-vault"))
    import network
    monkeypatch.setattr(network, "EVENT_LOG", tmp_path / "events.log")          # the real probes run; their log goes to tmp
    script = tmp_path / "cli.py"
    script.write_text(CLI)
    calls = []

    class Done:
        returncode = 0

    c = _RealServerCase(_base_deps(claude_setup_argv=[sys.executable, str(script)],
                                   console_run=lambda argv, **kw: (calls.append(argv), Done())[1]))
    c.chvt_calls = calls
    c.tmp = tmp_path
    yield c
    if c.server.deps.get("claude_setup") is not None:       # type: ignore[attr-defined]
        c.server.deps["claude_setup"].cancel()               # type: ignore[attr-defined]
    c.close()


NEW_PAGES = ["/ai-setup", "/ai-setup/claude", "/network", "/sensors", "/chat", "/tools"]


@pytest.mark.parametrize("path", NEW_PAGES)
def test_every_new_page_needs_a_session_and_renders_with_one(case, path):
    status, location, _ = req(case, "GET", path, cookie=False)
    assert status == 303 and location.endswith("/login")
    status, _, body = req(case, "GET", path)
    assert status == 200 and "<html" in body.lower() and "baseline-nav" in body        # inside the shared navigation


@pytest.mark.parametrize("path", ["/ai-setup/paste", "/ai-setup/claude/start", "/chat/ask", "/network/tether"])
def test_every_new_action_refuses_a_request_without_a_session_and_stores_nothing(case, path):
    status, location, _ = req(case, "POST", path, {"name": "OPENAI_API_KEY", "value": SECRET, "scope": "admin", "question": "x"}, cookie=False)
    assert status in (303, 401)
    assert v.Vault(v.ADMIN_VAULT).names() == []


def test_a_pasted_key_goes_to_the_chosen_vault_and_is_never_shown_again(case):
    status, location, _ = req(case, "POST", "/ai-setup/paste", {"name": "OPENAI_API_KEY", "value": SECRET, "scope": "personal"})
    assert status == 303 and location.startswith("/ai-setup")
    assert v.Vault(v.PERSONAL_VAULT).get("OPENAI_API_KEY") == SECRET and v.Vault(v.ADMIN_VAULT).names() == []
    _, _, page = req(case, "GET", "/ai-setup")
    assert SECRET not in page and "OPENAI_API_KEY (USER_PERSONAL)" in page
    assert "Available" in page                                          # the provider now reads as configured


def test_an_unknown_secret_name_or_a_bad_scope_is_refused_and_nothing_is_stored(case):
    for fields in ({"name": "PATH", "value": SECRET, "scope": "admin"}, {"name": "OPENAI_API_KEY", "value": SECRET, "scope": "world"},
                   {"name": "OPENAI_API_KEY", "value": "short", "scope": "admin"}):
        req(case, "POST", "/ai-setup/paste", fields)
    assert v.Vault(v.ADMIN_VAULT).names() == [] and v.Vault(v.PERSONAL_VAULT).names() == []


def test_the_claude_sign_in_shows_the_link_takes_the_code_and_stores_the_token(case):
    status, location, _ = req(case, "POST", "/ai-setup/claude/start")
    assert status == 303 and location == "/ai-setup/claude"
    page = ""
    for _ in range(100):
        _, _, page = req(case, "GET", "/ai-setup/claude")
        if "claude.com/cai/oauth/authorize" in page:
            break
        time.sleep(0.1)
    assert 'href="https://claude.com/cai/oauth/authorize?code=true&amp;state=s1"' in page
    req(case, "POST", "/ai-setup/claude/code", {"code": "right-code-777"})
    for _ in range(100):
        if v.Vault(v.ADMIN_VAULT).get("CLAUDE_CODE_OAUTH_TOKEN"):
            break
        time.sleep(0.1)
    assert v.Vault(v.ADMIN_VAULT).get("CLAUDE_CODE_OAUTH_TOKEN") == "sk-ant-oat01-" + "Zq4" * 24
    _, _, after = req(case, "GET", "/ai-setup/claude")
    assert "sk-ant-oat01" not in after and "signed in" in after


def test_a_wrong_code_stores_nothing(case):
    req(case, "POST", "/ai-setup/claude/start")
    for _ in range(100):
        if "authorize" in req(case, "GET", "/ai-setup/claude")[2]:
            break
        time.sleep(0.1)
    req(case, "POST", "/ai-setup/claude/code", {"code": "nope"})
    time.sleep(1.0)
    assert v.Vault(v.ADMIN_VAULT).names() == []


def test_chat_without_a_provider_says_so_and_a_missing_question_is_refused(case, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    import harness
    monkeypatch.setattr(harness, "ENV_FILE", str(case.tmp / "absent.env"))
    status, location, _ = req(case, "POST", "/chat/ask", {"harness": "claude", "question": "how hot is the drive?"})
    assert status == 303 and location == "/chat"
    _, _, page = req(case, "GET", "/chat")
    assert "how hot is the drive?" in page and "no CLAUDE_CODE_OAUTH_TOKEN" in page
    status, location, _ = req(case, "POST", "/chat/ask", {"harness": "claude", "question": "   "})
    assert location.startswith("/chat?notice=")


def test_the_console_page_switches_the_screen_only_for_a_request_from_this_machine(case):
    status, _, body = req(case, "GET", "/console", cookie=False)            # loopback, no login needed
    assert status == 200 and "Show the Baseline console" in body
    status, location, _ = req(case, "POST", "/console/switch", cookie=False)
    assert status == 303 and case.chvt_calls == [["chvt", "1"]]


# --- Console tab parity and the OpenCode harness in the browser -----------------------------------------------------------------

def _context(adapters):
    from types import SimpleNamespace as NS
    import console_commands as cc
    registry = NS(get_adapter=lambda hid: adapters.get(hid), supports_write_grant=lambda a: False, HarnessAdapterError=RuntimeError)
    return cc.Context(hardware=None, network=None, tether=None, harness_registry=registry, sessions={}, snapshot={}, now=lambda: 1.0)


class _Adapter:
    def __init__(self, name):
        self.name, self.asked = name, []

    def new_session(self):
        return object()

    def ask(self, question, session=None):
        self.asked.append(question)
        return f"{self.name} says: {question}"


def test_the_browser_console_runs_commands_and_keeps_a_transcript(case):
    status, _, page = req(case, "GET", "/shell")
    assert status == 200 and "baseline&gt; help" not in page and 'action="/shell/run"' in page
    req(case, "POST", "/shell/run", {"line": "help", "harness": "claude"})
    req(case, "POST", "/shell/run", {"line": "bogus", "harness": "claude"})
    _, _, page = req(case, "GET", "/shell")
    assert "commands: hardware, network, tether" in page and "unknown command" in page and "baseline&gt; help" in page


def test_the_opencode_harness_is_reachable_from_chat_and_the_console(case):
    claude, opencode = _Adapter("claude"), _Adapter("opencode")
    case.server.deps["console_context"] = _context({"claude": claude, "opencode": opencode})     # type: ignore[attr-defined]
    req(case, "POST", "/chat/ask", {"harness": "opencode", "question": "list drives"})
    req(case, "POST", "/shell/run", {"line": "ask what is hot", "harness": "opencode"})
    assert opencode.asked == ["list drives", "what is hot"] and claude.asked == []
    _, _, chat = req(case, "GET", "/chat")
    _, _, shell = req(case, "GET", "/shell")
    assert "opencode says: list drives" in chat and "opencode says: what is hot" in shell


def test_the_console_refuses_an_oversized_line_and_requires_a_session(case):
    status, location, _ = req(case, "POST", "/shell/run", {"line": "help", "harness": "claude"}, cookie=False)
    assert status in (303, 401)
    req(case, "POST", "/shell/run", {"line": "x" * 5000, "harness": "claude"})
    _, _, page = req(case, "GET", "/shell")
    assert "x" * 100 not in page and "too long" in page


# --- Vault encryption at rest through the browser ---------------------------------------------------------------------------------

PASS = "a long vault passphrase 2026"


def test_the_vault_is_sealed_with_a_passphrase_and_unlocked_for_the_boot(case, monkeypatch):
    monkeypatch.setattr(v, "RUNTIME_DIR", str(case.tmp / "run-vault"))
    req(case, "POST", "/ai-setup/paste", {"name": "OPENAI_API_KEY", "value": SECRET, "scope": "admin"})
    assert v.Vault(v.ADMIN_VAULT).get("OPENAI_API_KEY") == SECRET                       # plain until a passphrase is set
    _, _, page = req(case, "GET", "/vault")
    assert "Set a vault passphrase" in page
    status, location, _ = req(case, "POST", "/vault/set", {"passphrase": PASS, "again": PASS})
    assert status == 303
    raw = (case.tmp / "admin-vault" / "OPENAI_API_KEY").read_text()
    assert raw.startswith("ENC1:") and SECRET not in raw                                # sealed on the drive
    _, _, page = req(case, "GET", "/vault")
    assert "Unlocked" in page and SECRET not in page and PASS not in page
    assert (case.tmp / "run-vault" / "OPENAI_API_KEY").read_text().strip() == SECRET        # plaintext only in the RAM-backed folder
    req(case, "POST", "/ai-setup/paste", {"name": "GEMINI_API_KEY", "value": "gemini-new-value-0002", "scope": "admin"})
    assert (case.tmp / "admin-vault" / "GEMINI_API_KEY").read_text().startswith("ENC1:")     # new secrets are sealed too
    req(case, "POST", "/vault/lock")
    assert not list((case.tmp / "run-vault").glob("*"))
    _, _, page = req(case, "GET", "/vault")
    assert "Locked" in page and "Unlock" in page
    req(case, "POST", "/vault/unlock", {"passphrase": "wrong passphrase 123456"})
    assert not list((case.tmp / "run-vault").glob("*"))
    req(case, "POST", "/vault/unlock", {"passphrase": PASS})
    assert (case.tmp / "run-vault" / "GEMINI_API_KEY").read_text().strip() == "gemini-new-value-0002"


def test_mismatched_or_short_passphrases_do_not_seal_anything(case, monkeypatch):
    monkeypatch.setattr(v, "RUNTIME_DIR", str(case.tmp / "run-vault"))
    req(case, "POST", "/ai-setup/paste", {"name": "OPENAI_API_KEY", "value": SECRET, "scope": "admin"})
    req(case, "POST", "/vault/set", {"passphrase": PASS, "again": PASS + "x"})
    req(case, "POST", "/vault/set", {"passphrase": "short", "again": "short"})
    assert v.Vault(v.ADMIN_VAULT).get("OPENAI_API_KEY") == SECRET and not v.Vault(v.ADMIN_VAULT).has_passphrase()


def test_a_sealed_vault_accepts_the_claude_token_once_unlocked(case, monkeypatch):
    monkeypatch.setattr(v, "RUNTIME_DIR", str(case.tmp / "run-vault"))
    req(case, "POST", "/vault/set", {"passphrase": PASS, "again": PASS})
    req(case, "POST", "/ai-setup/claude/start")
    for _ in range(100):
        if "authorize" in req(case, "GET", "/ai-setup/claude")[2]:
            break
        time.sleep(0.1)
    req(case, "POST", "/ai-setup/claude/code", {"code": "right-code-777"})
    for _ in range(100):
        if (case.tmp / "admin-vault" / "CLAUDE_CODE_OAUTH_TOKEN").exists():
            break
        time.sleep(0.1)
    raw = (case.tmp / "admin-vault" / "CLAUDE_CODE_OAUTH_TOKEN").read_text()
    assert raw.startswith("ENC1:") and "sk-ant-oat01" not in raw
    assert v.Vault(v.ADMIN_VAULT).get("CLAUDE_CODE_OAUTH_TOKEN", passphrase=PASS) == "sk-ant-oat01-" + "Zq4" * 24


@pytest.mark.parametrize("path", ["/vault/set", "/vault/unlock", "/vault/lock"])
def test_vault_actions_need_a_session(case, path):
    status, _, _ = req(case, "POST", path, {"passphrase": PASS, "again": PASS}, cookie=False)
    assert status in (303, 401) and not v.Vault(v.ADMIN_VAULT).has_passphrase()


def test_the_environments_page_lists_the_images_and_needs_a_session(case):
    assert req(case, "GET", "/environments", cookie=False)[0] == 303
    status, _, page = req(case, "GET", "/environments")
    assert status == 200 and "five guest applications" in page and "baseline-nav" in page
