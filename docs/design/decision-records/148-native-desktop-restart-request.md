# DR148 — Web action requests Ubuntu's native restart dialog

2026-10-04. Implemented; native dialog/restart verification pending.

The operator requested that host restart be initiated through the production
web application using the standard Ubuntu request and user confirmation.
The shared navigation now exposes Restart host. Its authenticated, same-origin
POST route discovers exactly one active local X11/Wayland session through
loginctl and invokes gnome-session-quit --reboot on that user's session bus.
The installed root web service uses runuser; the desktop development service
uses its own UID. It never passes --force or --no-prompt and never falls back
to systemctl reboot or ignores an inhibitor. GNOME owns confirmation/cancel
and any blocker presentation. Success means confirmation was requested, not
that the host rebooted. Missing/ambiguous desktop identity and command failures
are explicit errors. Existing web role restrictions, login and origin checks
apply; requests/results use the application's audit log.

The helper is included in provision.sh. RED was confirmed before implementation
(missing module); 72 focused tests passed, including real HTTP socket routing,
authentication refusal and synthetic session/command/error checks. These do
not verify that the actual Ubuntu dialog displayed or the host restarted.
The PC401 physical boot blocker remains open under DR146/REAL-013. Broader
production-web drive workflows remain open under v0.2 queue row78.

The existing desktop production web process was reloaded with its original
arguments, environment and working directory. Live HTTP returned 200 for
/login and redirected an unauthenticated POST /host/restart to /login (303),
without issuing a restart. The loaded action awaits the operator's authenticated
click and GNOME confirmation; no native dialog or successful reboot is claimed.

Reference: https://manpages.ubuntu.com/manpages/jammy/man1/gnome-session-quit.1.html

Follow-up: the operator reported the bare cross-site refusal after login, not
just after pressing Restart host. The shared no-referrer policy can turn form
POST Origin into null. It now uses same-origin, preserving local origin evidence
without sending referrers to other sites; origin matching and null/cross-site
refusals remain enforced. Restart submission additionally uses same-origin JSON
fetch and displays its response inline. 107 focused security/login/restart tests
pass; the shared policy regression failed before the fix. Actual browser login
and native restart confirmation await the operator's retry.
