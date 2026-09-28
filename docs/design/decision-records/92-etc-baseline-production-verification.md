# Decision record: real, root-created /etc/baseline confirms the PROTECTED-scope path end-to-end

Status: **verified. Closes the one item decision record 91 explicitly left open.**

## What was asked

"Yes, go ahead and set up /etc/baseline." Direct instruction to close decision record 91's one remaining gap: nobody had confirmed the PROTECTED-scope dependency checks actually *pass*, not just fail gracefully, against a real `/etc/baseline`.

## What happened

I don't have passwordless sudo and can't handle the user's password, so I could not run the setup myself - asked the user to run it in their own interactive terminal on the same machine:

```bash
sudo mkdir -p /etc/baseline/settings
sudo chown -R "$USER":"$USER" /etc/baseline
```

Confirmed created (`ls -ld` showed the real directory, owned by the real user). Re-ran `drive_admin.run_health_check(None)` for real against the real default paths - all four seed dependencies now report `ok`, including the two PROTECTED-scope ones (`install.self_installer_lvm_preset_valid`/`fqdn_valid`) that previously failed gracefully in decision record 90 for lack of this exact directory.

Inspected both real physical databases directly to confirm the GLOBAL/PROTECTED split is actually happening as designed, not just passing by coincidence:

- `/etc/baseline/settings/master_config.db` (PROTECTED) holds the `self_installer.lvm_size_preset`/`fqdn` **setting** entries.
- `/mnt/BASELINE/registry/foundation.db` (GLOBAL) holds the `dependencies` type's **definitions and check-result events** - including the results of checks that themselves read the PROTECTED-scope settings above.

This is the concrete, real proof of the architecture decision record 89 described: a dependency's own definition and history survive independent of USER_PERSISTENCE (GLOBAL), while correctly still being able to read a PROTECTED-scope value when that volume *is* available - two different scopes, two different files, cooperating correctly in one real check.

## Verification performed

- Real (non-test, non-fake) invocation of `drive_admin.run_health_check(None)` before and after, on the same machine, with the only variable being `/etc/baseline`'s existence - before: 2 of 4 checks failed gracefully; after: 4 of 4 pass.
- Direct `sqlite3` inspection of both real database files' contents, confirming the scope split is real and not incidental.
- Full unit suite re-run after: 1420/1420, unchanged - this was a real-environment verification step, not a code change.
