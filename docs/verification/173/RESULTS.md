# DR173 verification

Command:

```text
/home/cane/Applications/.venv/bin/python tests/integration/verify_installer_desktop_browser.py
```

Result: PASS in real Chromium against local HTTP using synthetic drive
discovery and a synthetic privileged executor. Assertions cover the named
environment settings modal, editable draft name, protected-drive disablement,
serial selection for the reviewed update workflow, OS/name selection in the
canonical Installer Plan, application selection, captured app configuration,
and the existing desktop interactions/copy/move behavior.

Focused unit checks:

```text
/home/cane/Applications/.venv/bin/python -m pytest -q tests/unit/test_installer_desktop.py tests/unit/test_install_plan_page.py
22 passed
```

`git diff --check` passed. No physical disk write, installed Proxmox boot,
firewall/network acceptance, guest workload provisioning, or persistent overlay
verification occurred. The verification namespace exposed serial inventory but
no `/dev` block-device nodes. Screenshots from DR172 show the corresponding
desktop, phone-width, Object Manager, and modal UI: [evidence](../172/AUDIT.md).
