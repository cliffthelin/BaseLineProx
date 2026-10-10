# Decision record 178: keep the development Installer local

Date: 2026-10-09
Status: implemented and verified on the development host.

## Finding and correction

The desktop launcher started `baseline_web.py` directly when no installed
`baseline-web.service` existed. The real development process listened on
`0.0.0.0:8100`, while this environment had no verified host firewall policy.
That made the local test server reachable on every interface. The listener was
stopped immediately.

The uninstalled desktop-launcher path now supplies
`BASELINE_WEB_BIND_HOST=127.0.0.1`. `baseline_web.main()` honors that setting
and reports the configured address. The installed `baseline-web.service`
explicitly retains its LAN bind (`0.0.0.0`); that production path relies on the
existing active LAN-only firewall readiness gate and must not be called
internet-safe without that gate's runtime proof.

## Verification

The new launcher regression test failed before the implementation because the
direct-launch subprocess received no bind-host setting. The same test passed
after the fix, invoked without pytest scratch files or CACHE artifacts. The
actual desktop launcher was then run and `ss -ltnp` observed
`127.0.0.1:8100`; it did not listen on all interfaces. The route
`/install-plan` returned `303` to `/login`, so this fresh app process is not
authenticated. No operator credential was handled and no PC601 operation was
started.

This verifies the real development listener only. It does not verify the
installed service, its firewall, or PC601's network/GUI. No disk was written.
