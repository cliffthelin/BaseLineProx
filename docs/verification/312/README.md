# Optional AI setup verification — 2026-10-19

- Focused source/unit set: **347 passed**, including real encrypted temporary
  files, temporary SQLite drafts, local HTTP and a real launcher subprocess.
  Native Proxmox/LXC/Kasm transports in these tests use injected boundaries.
- Later targeted provider/harness/profile checks: **53 passed**; the final vault,
  profile and HTTP subset passed **70 checks**. Shell syntax,
  Python compilation and `git diff --check` passed.
- `tests/integration/verify_ai_installer_browser.py` passed in actual headless
  Chromium: 14 catalog entries, masked custom-key entry, encrypted save,
  reference-only draft, reload, empty credential fields after save and opt-out.
- [Screenshot](installer-ai-setup.png): synthetic credential already cleared.
- No real provider token was imported, inspected or tested; no API request or
  native guest/workspace deployment was executed. No QEMU test was run.

## Physical deployment

**Pending native desktop authentication.** The prepared code-only command is:

```
pkexec /usr/bin/python3 /tmp/baseline-ai-feature-deploy.py
```

Its existing system authentication prompt must complete before code can be
installed on PC601 and BASELINE_MIRROR. This is a native host privilege boundary,
not a request for the agent to receive or type a password. No deployment mount
or write has occurred while that prompt is pending.

On success the helper creates a unique `CACHE/baseline-build/ai-feature-TIMESTAMP`
folder containing a frozen source snapshot, original system-code backups and a
per-copy SHA256 report. It validates the source serial and role policy and the
mirror volume identity; it installs only code and an enabled offline timer,
then unmounts. It never opens an operator credential profile. The final report
must be checked before describing physical code deployment as complete.

## Still open

Real native boot, guest agent/Python/client prerequisites, provider account
reauthorization and actual VM/LXC/Kasm delivery remain acceptance work under
queue72/78. The general web fresh-build executor remains queue72/76. Exact
native identities for Muse/Grokbot/DeepSeekHarness were requested; their custom
configuration route is offered without claiming native adapters are complete.
Native token refreshes remain in RAM; durable resealing of changed client state
requires a later capture/re-import before reboot.

2026-10-19 deployment update: desktop authentication succeeded. Physical code
installation and byte checks completed on PC601 and BASELINE_MIRROR; report:
`/run/media/cane/CACHE/baseline-build/ai-feature-20261019T211020/report.json`.
Claude history and editable checkout were subsequently relocated to APPDATA_ADMIN
on both copies, with checksum comparison before removal of USER_ADMIN originals:
`/run/media/cane/CACHE/baseline-build/claude-appdata-20261019T211329/report.json`.
Both report 2081 history files / 809320287 bytes. All deployment mounts were
unmounted. Native boot, provider authentication, Claude resume and guest delivery
remain unverified. DR313 supersedes the earlier pending-deployment checkpoint.
