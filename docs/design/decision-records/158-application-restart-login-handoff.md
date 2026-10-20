# DR158 — Application restart awaiting interactive login

2026-10-04 local. Continues DR148/DR157 at the operator's explicit instruction
to restart the host through the application.

The live application responds HTTP 200 at /login on port 8100. Opened its
/drive-admin page in the existing desktop browser, first at 127.0.0.1 and then
localhost to allow a pre-existing hostname-scoped session. Desktop accessibility
inspection finds the browser at Log in, without the Restart host control.
No account password, browser cookie or session token was read, typed or stored.
No replacement authenticated session was generated or injected. A mistaken
X11 window match was VS Code rather than the browser; its temporary screenshot
was removed without inspection. Browser navigation used the existing session.

The operator must sign in directly in the browser before the agent can submit
/host/restart through the authenticated application. Interactive login has been
requested; no restart POST, native restart dialog or host restart is claimed.
The application keeps its existing authentication, role and same-origin checks.
No direct gnome-session-quit/systemctl reboot fallback bypassed that workflow.

PC401 boot remains blocked under DR157/DR146/queue78. Once authenticated, use
the actual Restart host control and retain Ubuntu's native confirmation and
inhibitor handling. After the host returns, re-resolve the serial/mount holders
before resuming the guarded boot-only verifier. This is a pending application
handoff, not completion of either restart or boot verification. INSTALL and
SESSION_HANDOFF are updated; prior decision records remain historical.
