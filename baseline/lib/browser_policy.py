"""Generates Chromium's managed-policy JSON for the Track B3 kiosk GUI
proof (Milestone 2 - see docs/design/milestone-2-gui-plan.md). Pure - no
subprocess, no file I/O here; the caller writes the returned dict as JSON
to /etc/chromium/policies/managed/baseline.json, which Debian's chromium
package reads on its own.

Scopes the browser to exactly the intended app (`URLAllowlist`), routes
downloads to the Baseline-controlled exchange directory the file-picker/
download-export broker also uses (`DownloadDirectory`, no location
prompt), and disables sign-in/sync/password-manager/default-browser
prompts that make no sense for a locked-down kiosk session.
"""
from __future__ import annotations


def generate(*, allowed_urls: list[str], download_directory: str) -> dict:
    if not allowed_urls:
        raise ValueError("allowed_urls must not be empty - a kiosk policy with no allowlist allows nothing intentional")
    return {
        "URLAllowlist": list(allowed_urls),
        "DownloadDirectory": download_directory,
        "PromptForDownloadLocation": False,
        "BrowserSignin": 0,
        "SyncDisabled": True,
        "PasswordManagerEnabled": False,
        "DefaultBrowserSettingEnabled": False,
    }
