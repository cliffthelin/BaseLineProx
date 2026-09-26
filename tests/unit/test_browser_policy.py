"""Unit tests for browser_policy.py (Track B3) - the pure function that
generates Chromium's managed-policy JSON. No subprocess, no real file I/O
in the function itself - the caller writes the returned dict as JSON."""
import browser_policy as bp


def test_generate_sets_url_allowlist():
    policy = bp.generate(allowed_urls=["https://example.test/"], download_directory="/var/lib/baseline/gui-exchange")
    assert policy["URLAllowlist"] == ["https://example.test/"]


def test_generate_sets_download_directory_and_disables_prompt():
    policy = bp.generate(allowed_urls=["https://example.test/"], download_directory="/var/lib/baseline/gui-exchange")
    assert policy["DownloadDirectory"] == "/var/lib/baseline/gui-exchange"
    assert policy["PromptForDownloadLocation"] is False


def test_generate_sets_privacy_safety_defaults():
    policy = bp.generate(allowed_urls=["https://example.test/"], download_directory="/tmp/x")
    assert policy["BrowserSignin"] == 0
    assert policy["SyncDisabled"] is True
    assert policy["PasswordManagerEnabled"] is False
    assert policy["DefaultBrowserSettingEnabled"] is False


def test_generate_accepts_multiple_allowed_urls():
    policy = bp.generate(allowed_urls=["https://a.test/", "https://b.test/"], download_directory="/tmp/x")
    assert policy["URLAllowlist"] == ["https://a.test/", "https://b.test/"]


def test_generate_rejects_empty_allowed_urls():
    import pytest
    with pytest.raises(ValueError):
        bp.generate(allowed_urls=[], download_directory="/tmp/x")


def test_generate_is_json_serializable():
    import json
    policy = bp.generate(allowed_urls=["https://example.test/"], download_directory="/tmp/x")
    json.dumps(policy)  # must not raise
