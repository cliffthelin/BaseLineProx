# DR170 verification

- Confirmed RED/GREEN: fresh desktop and expanded taskbar, direct menu, saved
  workspace overridden by explicit desktop URL.
- Real Chromium mouse/touch interaction script passed, synthetic privileged
  execution and disk fixtures; no physical deployment proof.
- 100 focused HTTP/configuration tests passed in 16.44 seconds.
- Native read-only discovery/autofill/catalog: two drives, five apps; environment
  fields name/os/variant. Sandbox boot identity was inconclusive, not absence.
- Real server reloaded and explicit desktop URL opened. Operator-screen
  acceptance is not established by launching the browser.
- Physical boot/workload/driver verification remains open.

After the explicit desktop launch, the live owner-scoped layout store contained
one display record with mode desktop, revision 2 and one page. This confirms
the signed-in live browser executed the display flow and saved its preference;
only these noncredential layout fields were read. It does not replace visual
operator acceptance.
