# DR167 verification — 2026-10-07

- New installed-update tests: confirmed RED before helper/action implementation;
  missing-input and existing-source-symlink regressions each confirmed RED.
- Recovery-inspection and repeat-boot firewall regressions each confirmed RED.
- Focused installed-update/workload tests: 17 passed (fake commands, local HTTP).
- Action bindings and RAM action-permission tests: 67 passed (synthetic disk).
- Firstboot and merged web checks: 115 passed (fakes, local HTTP).
- Initial complete regression: 3438 passed, 1 failed due to the allowlist fixture
  omitting the new action's required inputs. Fixture now supplies complete inputs
  and preserves the unchanged unauthorized-drive refusal/no-command assertions.
- Final complete regression: **3441 passed** in 165.64 seconds; no skips or
  deselections. Full output: /tmp/baseline-167-tests.txt. git diff --check passed.
- Real development-host Installer login: HTTP200, Referrer-Policy same-origin.
- Actual disk read-only identity/marker/fstab inspection only. No physical write,
  operator credential handling, new QEMU run or physical boot acceptance.
