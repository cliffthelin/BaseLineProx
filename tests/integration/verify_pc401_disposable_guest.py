#!/usr/bin/env python3
"""Real mounts, openssl and production HTTP in an explicitly disposable QEMU.

Runs in the Proxmox installer live environment, not on an installed host.
No disk formatting, network egress, mocked commands, or operator credentials.
Requires the sole test drive to have serial CODEXTEST40101. Source is carried
read-only on a separate test ISO; results may be sent to /dev/ttyS0.
The installer shell must have loopback enabled (ip link set lo up).
"""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import time


def command(argv):
    return subprocess.run(argv, check=True, text=True, capture_output=True, timeout=60).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    if (os.geteuid() != 0 or os.environ.get("BASELINE_DISPOSABLE_QEMU_ACCEPTANCE") != "1"
            or command(["lsblk", "-dn", "-o", "SERIAL", "/dev/vda"]) != "CODEXTEST40101"):
        raise RuntimeError("This check requires the explicitly disposable QEMU test drive")
    sys.path.insert(0, str(args.source_root / "baseline/lib"))
    import layered_settings as ls
    import persist_bind_mounts as pbm
    from repair import RealRunner
    import vault_crypto

    checks = []
    mounted = []
    runner = RealRunner()
    with tempfile.TemporaryDirectory(prefix="pc401-runtime-", dir="/run") as directory:
        root = Path(directory)

        def mount_tmpfs(path):
            path.mkdir()
            command(["mount", "-t", "tmpfs", "-o", "size=16m", "pc401-test", str(path)])
            mounted.append(path)
            return path

        try:
            volumes = [mount_tmpfs(root / name) for name in ("admin", "user", "appdata", "session")]
            roots = ls.Roots(*map(str, volumes), require_mount=True)
            ls.write_layer(roots, "admin", {"timezone": "America/Denver"}, actor="admin")
            ls.write_layer(roots, "user", {"theme": "dark"})
            ls.write_layer(roots, "os", {"keyboard": "de"}, os_id="O_V_00001")
            first, second = ls.effective_os(roots, "O_V_00001"), ls.effective_os(roots, "O_V_00002")
            assert first == {"timezone": "America/Denver", "theme": "dark", "keyboard": "de"}
            assert second == {"timezone": "America/Denver", "theme": "dark"}
            checks.append({"check": "shared_settings_on_real_mounted_volumes", "ok": True})
            command(["umount", str(volumes[1])])
            mounted.remove(volumes[1])
            try:
                ls.read_layer(roots, "user")
                raise AssertionError("unmounted settings were accepted")
            except ls.SettingsError:
                checks.append({"check": "unmounted_settings_refused", "ok": True})

            # The same production helper used before binding Proxmox's state.
            readonly = mount_tmpfs(root / "readonly")
            source = readonly / "host-state"
            source.mkdir()
            (source / "config").write_text("retain-this-state")
            command(["mount", "-o", "remount,ro", str(readonly)])
            destination = volumes[0] / "host-state"
            failed = pbm.migrate_redirect_contents(runner, str(source), str(destination))
            assert not failed.applied
            assert (source / "config").read_text() == "retain-this-state"
            assert (volumes[0] / ".host-state.migration-pending").exists()
            checks.append({"check": "real_mv_failure_leaves_migration_pending", "ok": True})
            command(["mount", "-o", "remount,rw", str(readonly)])
            # mv copied before its read-only unlink failed. Explicitly clear
            # that known disposable duplicate; production never guesses.
            assert (destination / "config").read_text() == "retain-this-state"
            collision = pbm.migrate_redirect_contents(runner, str(source), str(destination))
            assert not collision.applied and "collision" in collision.detail
            (destination / "config").unlink()
            complete = pbm.migrate_redirect_contents(runner, str(source), str(destination))
            assert complete.applied and not (source / "config").exists()
            assert (destination / "config").read_text() == "retain-this-state"
            command(["mount", "--bind", str(destination), str(source)])
            mounted.append(source)
            assert (source / "config").read_text() == "retain-this-state"
            checks.append({"check": "migration_retry_and_real_bind_retain_state", "ok": True})

            # Fresh disposable values only; no human vault or passphrase.
            passphrase, plaintext = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            sealed = vault_crypto.seal(plaintext, passphrase)
            assert plaintext not in sealed
            assert vault_crypto.open_sealed(sealed, passphrase) == plaintext
            try:
                vault_crypto.open_sealed(sealed, secrets.token_urlsafe(32))
                raise AssertionError("wrong passphrase accepted")
            except vault_crypto.WrongPassphrase:
                checks.append({"check": "real_openssl_vault_roundtrip_and_refusal", "ok": True})

            # Production server/dependencies, actual kernel/filesystem probes.
            # Issuing a disposable application session tests route behavior;
            # it does not prove PAM authentication or Proxmox GUI login.
            import baseline_web
            server = baseline_web.build_real_server(host="127.0.0.1", port=0,
                data_path=root / "web-store.json", state_dir=root / "web-state")
            session = server.deps["sessions"].create("qemu-test", time.time(), role="admin")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for path in ("/home", "/tools", "/environments", "/network", "/sensors", "/launcher", "/vault", "/ai-setup", "/power"):
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=90)
                    try:
                        connection.request("GET", path, headers={"Cookie": "session=" + session.token})
                        response = connection.getresponse()
                        body = response.read()
                        assert response.status in (200, 503), (path, response.status)
                        assert body, path
                        checks.append({"check": "production_http", "path": path, "status": response.status,
                            "body_sha256": hashlib.sha256(body).hexdigest(), "ok": True})
                    finally:
                        connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        except Exception as exc:
            print(json.dumps({"ok": False, "error": type(exc).__name__ + ": " + str(exc), "checks": checks}), flush=True)
            raise
        finally:
            for path in reversed(mounted):
                command(["umount", str(path)])
    print(json.dumps({"scope": "QEMU live installer; actual mounts, crypto and HTTP; no installed Proxmox or physical acceptance",
        "ok": True, "checks": checks}), flush=True)


if __name__ == "__main__":
    main()
