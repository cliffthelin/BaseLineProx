# Decision record: Drive Administration now authorizes actions via real `pkexec`/PolicyKit, not an HTML password form

Status: **implemented and fully unit-tested (1522/1522 full suite).
Live-verified: `pkexec whoami` genuinely returned `root` after the
operator authenticated through GNOME Shell's own native dialog on
this real machine, with the password never touching this process, this
web app's code, or any HTTP request. Modal UI confirmed live to no
longer render a password field.**

## What this resolves

Direct instruction, 2026-09-29: "Make the application ask for the
sudo password through Ubuntu best practices... This is not something
unusual for applications to do... not by being creative but by
following documented methods and policies from the OS provider." A
prior request to "just run the destructive action yourself" was
correctly refused (Claude never types or handles real system
passwords, no matter how directly asked) - this is the actual, real
fix the refusal was pointing toward: the web app itself now asks for
elevated privilege the same way GParted, GNOME Disks, and the Software
installer do, rather than collecting a password in an HTML form field
and piping it through `sudo -S`.

## Why this is a real improvement, not just a different UI

The prior mechanism (`SudoRunner`, decision records 84/100/101) worked,
but the password traveled through this web app's own code: typed into
an HTML `<input type="password">`, sent as a JSON field in a POST body
to this app's own HTTP handler, then piped to `sudo -S` via stdin. All
of that happens over `localhost` in this deployment, but it's still
real password material passing through code this project wrote and
could have a bug in.

`pkexec` removes that path entirely. PolicyKit's own authentication
agent - confirmed live on this machine to be GNOME Shell's own
built-in one, no separate `polkit-gnome-authentication-agent-1`
process needed - collects the password directly via a native OS
dialog, entirely outside the browser and outside this app's own
request/response cycle. This app's own code never sees, holds, or
transmits the password at any point. Verified directly: `pkexec
whoami` returned `root` after the operator authenticated through that
real dialog, with `subprocess.run(["pkexec", "whoami"], ...)` never
touching a password anywhere in its own call.

No custom PolicyKit `.policy` action file was needed - the built-in
default `org.freedesktop.policykit.exec` action (shipped by
`policykit-1` itself) already covers "run this specific command as
root, with interactive authentication," which is exactly what this
project's own `run`/`makedirs`/`tee`/`mv`/`rm` style privileged calls
need.

## What changed

- New `drive_admin.pkexec_argv`/`PkexecRunner`/`_PkexecPdsAdapter` -
  parallels `sudo_argv`/`SudoRunner`/`_SudoPdsAdapter` exactly (same
  `repair.Runner`-compatible interface, same `as_pds_runner()`
  bridge), but wraps every privileged call in `pkexec` instead of
  piping a password through `sudo -S -k -p ''`. `SudoRunner`/
  `verify_sudo_password` are unchanged and still real - login
  (`settings_web.SudoPasswordVerifier`, decision record 100) still
  uses them directly, since "does this browser session belong to
  someone who knows the password" is a genuinely different real
  question than "authorize this one destructive action," and a web
  login form is the normal, expected way to answer the first one.
- `baseline_web.py`'s `POST /drive-admin/action` no longer accepts or
  checks a `password` field at all - it constructs a `PkexecRunner()`
  directly and dispatches into the same async job/progress-console
  machinery (decision record 102) unchanged. A cancelled or failed
  native authentication surfaces as the underlying privileged
  command's own non-zero exit code, which the existing
  `ActionResult`/job flow already reports as a clean refusal - no new
  special-cased error path needed.
- The modal's password `<input>` field is gone entirely; its hint text
  now says a real native dialog will ask separately, never typed into
  the page.

## Files changed

- `baseline/lib/drive_admin.py` - `pkexec_argv`, `PkexecRunner`,
  `_PkexecPdsAdapter` added; `SudoRunner`/`_SudoPdsAdapter`/
  `verify_sudo_password` untouched.
- `baseline/lib/baseline_web.py` - `/drive-admin/action` POST handler
  rewritten (no password field/check, constructs `PkexecRunner`
  directly); modal HTML/JS - password `<input>` and every reference to
  it removed; `build_real_server`'s own docstring updated;
  `deps["sudo_executor"]` renamed to `deps["pkexec_executor"]`.
- Tests: `test_drive_admin.py` (8 new - `pkexec_argv`/`PkexecRunner`'s
  full interface, mirroring the existing `SudoRunner` test style,
  including proving no password is ever sent anywhere), 
  `test_baseline_web.py` (3 tests rewritten for the new model: a
  cancelled/failed native auth reports a real refusal not a 401; the
  page no longer renders a password field; the server genuinely
  dispatches through a real `PkexecRunner`, proven via `repair` -
  `update_selected`'s own honest placeholder never touches the runner
  at all, so it couldn't prove this).

## Real, disclosed side effect

`build_self_installer`'s "reuse your submitted password as the new
Proxmox root password" feature (this same day's earlier work) depended
on `SudoRunner.password` being available to forward. `PkexecRunner`
has no password attribute at all - by design, this process genuinely
never has access to the plaintext. Through the normal web-driven path,
`build_self_installer` now falls back to its original behavior:
generating and clearly surfacing a fresh one-time password (still
fixed to display as clean text, not a bytes-repr, and still shown live
in the progress console and the final result). This is an unavoidable,
direct consequence of the security improvement - the web app process
correctly no longer holds a value it has no business holding.

## Verification performed

- Full suite: 1522/1522 (was 1514 before this record's 11 new tests).
- `tools/check_provision_deploys_all_imports.py`: OK.
- `tests/unit/test_no_persistence_typo.py`: 6/6.
- **Live, real verification, not just unit tests**: `pkexec whoami`
  run directly against this machine's real GNOME session genuinely
  returned `root` after the operator authenticated through the native
  dialog - confirmed by the operator directly ("It did and I provided
  it"). Server restarted on the new code; the running page's modal
  confirmed via live DOM inspection to have no password field at all,
  while the confirm button and progress console remain present.
- Not yet verified: a real, full Drive Administration action (e.g.
  `repair` or `build_self_installer`) actually triggering the native
  dialog and completing successfully end-to-end through the running
  web app, as opposed to the standalone `pkexec whoami` proof and the
  unit-test-level dispatch proof. The operator should try a real
  action next and confirm the dialog appears and the action completes.
