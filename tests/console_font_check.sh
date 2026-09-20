#!/bin/bash
# Regression check for the console font/glyph-map corruption found
# 2026-09-20: an earlier ungraceful exit of baseline.service left tty1's
# loaded font corrupted - real text rendered as wrong/missing characters
# ("garble"), even though systemd's TTYReset/TTYVHangup had already run.
# Those reset termios flags (line discipline, echo, raw mode) - neither
# touches the kernel's loaded console font/Unicode glyph-mapping table,
# which is the thing that was actually broken.
#
# baseline.service's ExecStartPre already reloads the font on every
# start/restart, so a normal deploy (scp + `systemctl restart`) already
# fixes this as a side effect. This script is the standalone, re-runnable
# version of that same check - run it directly after any deploy to
# verify (and fix, if needed) the font without relying on remembering to
# restart the service, and without waiting for the next boot.
#
# There's no real way to non-invasively detect *whether* the font is
# currently corrupted (the kernel doesn't expose "is my glyph table
# sane"). setfont is cheap and idempotent, so the check is: does loading
# the known-good font onto tty1 succeed. Run as root (setfont needs
# access to the console device).
set -uo pipefail

FONT="/usr/share/consolefonts/Lat15-Fixed16.psf.gz"
TTY="/dev/tty1"

echo "=== Console font check: $TTY ==="

if [ ! -f "$FONT" ]; then
    echo "FAIL: expected font file missing: $FONT"
    echo "      (check /etc/default/console-setup for the configured FONTFACE/FONTSIZE/CODESET"
    echo "      if this image uses a different font than Lat15-Fixed16)"
    exit 1
fi

ERR="$(mktemp)"
if setfont "$FONT" -C "$TTY" 2>"$ERR"; then
    echo "PASS: $FONT loaded cleanly on $TTY"
    rm -f "$ERR"
    exit 0
else
    echo "FAIL: setfont could not load $FONT on $TTY:"
    cat "$ERR"
    rm -f "$ERR"
    exit 1
fi
