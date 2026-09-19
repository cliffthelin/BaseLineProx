#!/bin/bash
# Baseline harness auth setup.
# Runs `claude setup-token` interactively (you still open the URL and log
# in normally), then automatically captures the resulting token and writes
# it to /etc/baseline/harness.env - no manual copy/paste of the token.
set -euo pipefail

LOG="$(mktemp)"
trap 'shred -u "$LOG" 2>/dev/null || rm -f "$LOG"' EXIT

echo "Starting Claude Code auth setup."
echo "Open the URL it prints, sign in, and paste the code back here as usual."
echo

script -qec "claude setup-token" "$LOG"

TOKEN="$(grep -oE 'sk-ant-oat01-[A-Za-z0-9_-]+' "$LOG" | tail -1 || true)"

if [ -z "$TOKEN" ]; then
    echo
    echo "No token found in the output above - setup did not complete. Nothing was saved."
    exit 1
fi

mkdir -p /etc/baseline
printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' "$TOKEN" > /etc/baseline/harness.env
chmod 600 /etc/baseline/harness.env

echo
echo "Saved to /etc/baseline/harness.env (${#TOKEN} characters, starts with sk-ant-oat01-)."
