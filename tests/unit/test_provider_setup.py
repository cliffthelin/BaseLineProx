"""Browser-guided provider sign-in: the provider's own CLI runs under a terminal, its sign-in link is shown to the person, the code they
get back is passed to it, and the token it prints goes straight into the vault. A real child process (a stand-in for the CLI that
behaves like `claude setup-token`), real pty, real vault files; the token never appears in any state the page can read."""
import sys
import time

import pytest

import provider_setup as ps
import vault as v

TOKEN = "sk-ant-oat01-" + "Qw7" * 24

CLI = r'''
import sys
print("Welcome to the CLI")
print("Open this URL to sign in:")
print("https://claude.com/cai/oauth/authorize?code=true&client_id=abc&state=xyz", flush=True)
code = sys.stdin.readline().strip()
if code != "good-code-123":
    print("Invalid code", flush=True)
    sys.exit(1)
print("Your token:")
print("sk-ant-oat01-" + "Qw7" * 24, flush=True)
'''


def wait_for(session, phase, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        if session.state()["phase"] == phase:
            return session.state()
        time.sleep(0.05)
    raise AssertionError(f"never reached {phase}: {session.state()}")


@pytest.fixture
def cli(tmp_path):
    path = tmp_path / "fake_cli.py"
    path.write_text(CLI)
    return [sys.executable, str(path)]


def make(cli, tmp_path):
    vault = v.Vault(tmp_path / "vault")
    return ps.GuidedSetup(cli, vault, "CLAUDE_CODE_OAUTH_TOKEN", allowed_url_prefix="https://claude.com/"), vault


def test_the_sign_in_link_is_found_the_code_is_passed_and_the_token_lands_in_the_vault(tmp_path, cli):
    session, vault = make(cli, tmp_path)
    session.start()
    state = wait_for(session, "waiting_for_code")
    assert state["url"].startswith("https://claude.com/cai/oauth/authorize?")
    session.submit_code("good-code-123")
    done = wait_for(session, "done")
    assert vault.get("CLAUDE_CODE_OAUTH_TOKEN") == TOKEN
    assert TOKEN not in repr(done) and TOKEN not in repr(session.state())


def test_a_wrong_code_fails_and_stores_nothing(tmp_path, cli):
    session, vault = make(cli, tmp_path)
    session.start()
    wait_for(session, "waiting_for_code")
    session.submit_code("wrong")
    state = wait_for(session, "failed")
    assert state["message"] and "Invalid code" not in state["message"]          # the CLI's own output is never relayed
    assert vault.get("CLAUDE_CODE_OAUTH_TOKEN") is None and vault.names() == []


def test_a_link_to_another_site_is_never_shown(tmp_path):
    script = tmp_path / "evil.py"
    script.write_text('print("https://evil.example/phish", flush=True)\nimport time; time.sleep(5)\n')
    session = ps.GuidedSetup([sys.executable, str(script)], v.Vault(tmp_path / "v"), "CLAUDE_CODE_OAUTH_TOKEN",
                             allowed_url_prefix="https://claude.com/", wait_seconds=2)
    session.start()
    state = wait_for(session, "failed", 8)
    assert state["url"] is None
    session.cancel()


def test_codes_that_cannot_be_a_code_are_refused(tmp_path, cli):
    session, _ = make(cli, tmp_path)
    session.start()
    wait_for(session, "waiting_for_code")
    for bad in ("", "a\nb", "x" * 600, "\x00"):
        with pytest.raises(ps.SetupError):
            session.submit_code(bad)
    session.cancel()


def test_cancel_stops_the_child_and_a_missing_cli_is_a_clear_failure(tmp_path, cli):
    session, _ = make(cli, tmp_path)
    session.start()
    wait_for(session, "waiting_for_code")
    session.cancel()
    assert session.state()["phase"] == "cancelled"
    missing = ps.GuidedSetup(["/nonexistent/claude-cli"], v.Vault(tmp_path / "v2"), "CLAUDE_CODE_OAUTH_TOKEN",
                             allowed_url_prefix="https://claude.com/")
    missing.start()
    assert wait_for(missing, "failed")["message"]
