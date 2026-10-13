"""Real-tool check (no credentials, nothing stored): the real `claude setup-token` shows a sign-in link on claude.com that GuidedSetup
captures, and cancelling stops it. Run by hand: python3 tests/integration/verify_claude_signin_link.py"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "baseline/lib"))
import provider_setup as ps  # noqa: E402
import vault as v  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    vault = v.Vault(Path(tmp) / "vault")
    session = ps.GuidedSetup(["claude", "setup-token"], vault, "CLAUDE_CODE_OAUTH_TOKEN", allowed_url_prefix="https://claude.com/")
    session.start()
    end = time.time() + 45
    while time.time() < end and session.state()["phase"] in ("idle", "starting"):
        time.sleep(0.5)
    state = session.state()
    session.cancel()
    assert state["phase"] == "waiting_for_code", state
    assert state["url"].startswith("https://claude.com/"), state["url"][:40]
    assert vault.names() == []
    print("OK: sign-in link captured:", state["url"].split("?")[0])
