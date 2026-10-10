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
