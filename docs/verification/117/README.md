# DR117 evidence, 2026-10-01 local / 2026-10-02 UTC

These are actual VM screenshots and real guest/tool results. They are not
mockups. See [DR117](../../design/decision-records/117-real-ubuntu-proxmox-environment.md)
for procedure, failures and limits.

- `proxmox-kiosk.png`: Chromium in a real Proxmox clone displaying its actual
  login page. A transient Cage service used the corrected seat/TTY properties.
- `proxmox-ubuntu-console.png`: nested Ubuntu server on Proxmox's VM100 console.
- `ubuntu-login-greeter.png`: actual Ubuntu GDM greeter requiring the
  newly created baseline-admin login. This is an authenticated-access greeter,
  not evidence that the screenshot itself follows a login.
- `ubuntu-firefox-policy.png`: Firefox in the logged-in Ubuntu desktop showing
  its actual homepage policy. The fixture's homepage endpoint was absent in
  this direct-QEMU test (the other tab correctly says Problem loading page).
  Actual Proxmox page rendering is proved separately by the kiosk screenshot;
  nested Ubuntu HTTPS reachability is proved in `proxmox-live.json`.
- `ubuntu-desktop-*.json`: real guest agent facts before/after the OS rebuild.
- `ubuntu-home-after-rebuild.txt`: read-only retained-disk inspection showing
  the document and real Firefox profile preference after the rebuild.
- `proxmox-live.json`: actual versions, configurations and machine status;
  full standalone disk has no backing image; nested guest confirms retained
  document, separate /home and HTTP200 from the real Proxmox host endpoint.
  The standalone VM has only an allocated disk, not an installed OS.
- `web-checks.txt`: real HTTP authentication/storage/page checks, summarized.
- `source-sha256.json`: exact implementation source fingerprint for this proof.

Full guarded unit suite: **2839 passed** using
`python3 -m pytest -q tests/unit --basetemp .test-work-117`.
Unit VM runners are fakes; real socket unit checks still use fake hardware.
The separate running-VM checks above used actual QEMU/KVM, guest agents and
Proxmox tools. `python3 tools/check_provision_deploys_all_imports.py` and
`bash -n boot/provision.sh` passed. No bare-metal deployment or physical drive
write was performed. No passwords, password hashes, SSH keys or cloud-init seed contents
are stored in this evidence directory.
