import socket

import providers


def test_credential_file_read_failure_is_not_reported_as_unconfigured(monkeypatch):
    def denied(_self):
        raise PermissionError("credential file denied")

    monkeypatch.setattr(providers.Path, "read_text", denied)
    monkeypatch.setattr(providers.os.path, "exists", lambda _path: True)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

    result = providers.check_providers()

    claude = next(item for item in result if item["name"] == "Claude Subscription")
    assert claude["state"] == "unknown"
    assert "credential file denied" in claude["detail"]


def test_empty_credential_assignment_is_not_reported_as_configured(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(providers.os.path, "exists", lambda _path: True)
    monkeypatch.setattr(providers.Path, "read_text", lambda _self: "OPENAI_API_KEY=\n")

    result = providers.check_providers()

    openai = next(item for item in result if item["name"] == "OpenAI")
    assert openai["state"] == "unconfigured"


def test_configured_claude_token_is_not_claimed_live_verified(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-token")

    result = providers.check_providers()

    claude = next(item for item in result if item["name"] == "Claude Subscription")
    assert claude["state"] == "available"
    assert "not checked" in claude["detail"]
    assert "verified live" not in claude["detail"]


def test_unknown_provider_observation_displays_unknown():
    assert providers.display_status("unknown") == "Unknown"


def test_unrecognized_provider_state_fails_closed_in_dashboard():
    assert providers.display_status("unexpected-state") == "Unknown"


def test_ollama_timeout_is_unknown_not_unconfigured(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise TimeoutError("probe timed out")

    monkeypatch.setattr(providers.socket, "create_connection", timeout)
    result = providers.check_providers()
    ollama = next(item for item in result if item["name"] == "Ollama (local)")
    assert ollama["state"] == "unknown"
    assert "timed out" in ollama["detail"]


def test_ollama_refused_connection_is_not_claimed_configured(monkeypatch):
    def refused(*_args, **_kwargs):
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr(providers.socket, "create_connection", refused)
    result = providers.check_providers()
    ollama = next(item for item in result if item["name"] == "Ollama (local)")
    assert ollama["state"] == "unreachable"
    assert "refused" in ollama["detail"]


def test_a_provider_without_credentials_is_not_set_up_not_unreachable():
    """The operator read "Unreachable" as a network fault (2026-10-12); the network was fine and nothing was configured."""
    assert providers.display_status("unconfigured") == "Not set up"
    assert providers.display_status("unreachable") == "Unreachable"


def test_a_credential_in_the_vault_makes_the_provider_available(tmp_path, monkeypatch):
    import vault
    admin = vault.Vault(tmp_path / "admin")
    admin.put("OPENAI_API_KEY", "sk-test-value-0000000001")
    monkeypatch.setattr(vault, "default_vaults", lambda: [admin])
    monkeypatch.setattr(providers, "HARNESS_ENV_FILE", str(tmp_path / "absent.env"))
    for name in ("OPENAI_API_KEY",):
        monkeypatch.delenv(name, raising=False)
    assert providers._env_or_file("OPENAI_API_KEY") is True
    assert providers._env_or_file("GEMINI_API_KEY", "GOOGLE_API_KEY") is False


def test_harness_status_says_installed_and_credentialed_separately(monkeypatch):
    monkeypatch.setattr(providers, "_env_or_file", lambda *names: names == ("CLAUDE_CODE_OAUTH_TOKEN",))
    rows = {r["id"]: r for r in providers.harness_status(which=lambda b: "/usr/bin/" + b if b in ("claude", "codex") else None)}
    assert rows["claude"] == {"id": "claude", "name": "Claude Code", "installed": True, "credential": "set"}
    assert rows["codex"]["installed"] is True and rows["codex"]["credential"] == "missing"
    assert rows["opencode"]["installed"] is False and rows["opencode"]["credential"] == "not needed"
