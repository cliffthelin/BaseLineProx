"""The /ai-setup page: provider status, the guided Claude sign-in, and paste fields that go to the vault. Pure rendering and routing helpers;
the sign-in mechanics are proven in test_provider_setup with a real child process."""
import ai_setup_page as page
import vault as v


def test_every_provider_has_a_site_link_and_the_page_never_shows_a_value(tmp_path):
    admin = v.Vault(tmp_path / "admin")
    admin.put("OPENAI_API_KEY", "sk-live-value-should-never-render-1")
    html = page.render_overview([{"name": "OpenAI", "state": "available", "detail": "x"},
                                 {"name": "Claude Subscription", "state": "unconfigured", "detail": "y"}],
                                admin.status(), []).decode()
    assert "sk-live-value-should-never-render-1" not in html
    assert "https://platform.openai.com/api-keys" in html and "https://aistudio.google.com/app/apikey" in html
    assert "OPENAI_API_KEY" in html                        # the name and fingerprint are shown, not the value
    assert 'action="/ai-setup/claude/start"' in html and 'action="/ai-setup/paste"' in html


def test_only_known_provider_secret_names_and_scopes_are_accepted_for_paste():
    assert page.paste_target("OPENAI_API_KEY", "admin") == ("OPENAI_API_KEY", "admin")
    assert page.paste_target("GEMINI_API_KEY", "personal") == ("GEMINI_API_KEY", "personal")
    for name, scope in (("PATH", "admin"), ("OPENAI_API_KEY", "world"), ("../X", "admin"), ("", "admin")):
        try:
            page.paste_target(name, scope)
        except ValueError:
            continue
        raise AssertionError((name, scope))


def test_the_code_page_shows_the_providers_link_only_while_waiting():
    waiting = page.render_claude({"phase": "waiting_for_code", "url": "https://claude.com/cai/oauth/authorize?x=1", "message": "m"}).decode()
    assert 'href="https://claude.com/cai/oauth/authorize?x=1"' in waiting and 'action="/ai-setup/claude/code"' in waiting
    done = page.render_claude({"phase": "done", "url": "https://claude.com/x", "message": "signed in"}).decode()
    assert "https://claude.com/x" not in done and "signed in" in done
