"""TestPersistence Milestone 5: application-grant proof (docs/design/
testpersistence-prd.md acceptance cases 3, 7, 8).

Reuses Phase B's proven boot/login/LUKS helpers
(tools/testpersistence_phaseB_vertical_slice.py) rather than
duplicating them, and adds a minimal, REALLY ENFORCED access-broker
boundary: two synthetic application principals are separate Linux
system accounts with no login shell; a grant is enforced with plain
Unix ownership/permission changes (chown/chmod) on the collection
directory inside the mounted, LUKS2-encrypted persistence filesystem -
not a comment claiming isolation, an actual kernel-DAC boundary that
is tested by attempting reads as each principal and checking the
permission-denied/allowed outcome directly.

Neither application principal is ever given read access to the raw
block device (/dev/vdb, /dev/mapper/testpersistence001) or the LUKS
key file - checked explicitly, not assumed from "they're unprivileged
users" alone.
"""
import base64
import json
import os
import secrets
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qemu_harness_safety as h  # noqa: E402
import qemu_serial_console as console  # noqa: E402
from testpersistence_phaseB_vertical_slice import (  # noqa: E402
    Evidence, StepFailed, authorize, clean_shutdown, launch, login, run_cmd,
    sanitized_failure_message, wait_for_login_prompt, _EVIDENCE_HOLDER,
)

EXPERIMENT_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "experiments", "testpersistence-m5-grants", "experiment-root")
DOWNLOAD_CACHE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "experiments", "testpersistence-m5-grants", "download-cache")
BASE_IMAGE = os.path.join(
    DOWNLOAD_CACHE, "debian-13-genericcloud-amd64-20260914-2601.qcow2")

SYNTH_LOGIN_USER = "testoperator"

INIT_SCRIPT = r"""
import hashlib, hmac, json, sys
DOMAIN = b"baseline-manifest-test-v1:"
KEY = bytes.fromhex(sys.argv[1])

def canon(seq, event, payload, prev):
    return json.dumps({"sequence": seq, "event": event, "payload": payload,
                        "previous_mac": prev}, sort_keys=True).encode()

def mac(seq, event, payload, prev):
    return hmac.new(KEY, DOMAIN + canon(seq, event, payload, prev), hashlib.sha256).hexdigest()

entry0 = {"sequence": 0, "event": "store_created",
          "payload": {"logical_identity": "TestPersistence-001"}, "previous_mac": ""}
entry0["mac"] = mac(0, entry0["event"], entry0["payload"], "")

manifest = {
    "schema_version": 1, "test_only": True, "manifest_domain": DOMAIN.decode(),
    "logical_identity": "TestPersistence-001", "carrier_identity": "TestPersistenceDisk-001",
    "generation": 1,
    "namespaces": {
        "person": {"TestPerson-001": {"documents_ref": "TestDocuments"}},
        "application_state": {"TestApplication-A": {}, "TestApplication-B": {}},
        "grants": {},
    },
}
with open("/mnt/persistence/manifest.json", "w") as f:
    json.dump(manifest, f, indent=2)
with open("/mnt/persistence/ledger.json", "w") as f:
    json.dump([entry0], f, indent=2)
print("INIT_WRITTEN")
"""

GRANT_SCRIPT = r"""
import hashlib, hmac, json, sys
DOMAIN = b"baseline-manifest-test-v1:"
KEY = bytes.fromhex(sys.argv[1])
action, grant_id, person, application, collection, access_mode = sys.argv[2:8]

def canon(seq, event, payload, prev):
    return json.dumps({"sequence": seq, "event": event, "payload": payload,
                        "previous_mac": prev}, sort_keys=True).encode()

def mac(seq, event, payload, prev):
    return hmac.new(KEY, DOMAIN + canon(seq, event, payload, prev), hashlib.sha256).hexdigest()

with open("/mnt/persistence/ledger.json") as f:
    ledger = json.load(f)
with open("/mnt/persistence/manifest.json") as f:
    manifest = json.load(f)

seq = len(ledger)
prev = ledger[-1]["mac"] if ledger else ""
event = "grant_issued" if action == "issue" else "grant_revoked"
payload = {"grant_id": grant_id, "person": person, "application": application,
           "collection": collection, "access_mode": access_mode}
entry = {"sequence": seq, "event": event, "payload": payload, "previous_mac": prev}
entry["mac"] = mac(seq, event, payload, prev)
ledger.append(entry)

manifest["namespaces"]["grants"][grant_id] = {
    "person": person, "application": application, "collection": collection,
    "access_mode": access_mode, "duration": "until_revoked", "authorized_by": "broker",
    "effective": action == "issue",
}

with open("/mnt/persistence/ledger.json", "w") as f:
    json.dump(ledger, f, indent=2)
with open("/mnt/persistence/manifest.json", "w") as f:
    json.dump(manifest, f, indent=2)
print(f"GRANT_{action.upper()}_DONE")
"""


def send_script(con, script_text, filename):
    encoded = base64.b64encode(script_text.encode()).decode()
    out = run_cmd(con, f"echo {encoded} | base64 -d > {filename}", "SCRIPTXFERDONE", timeout=15)
    return "SCRIPTXFERDONE" in out


def main():
    os.makedirs(EXPERIMENT_ROOT, exist_ok=True)
    root = h.validate_experiment_root(EXPERIMENT_ROOT)

    login_password = secrets.token_urlsafe(24)
    luks_passphrase = secrets.token_urlsafe(24)
    manifest_key_hex = secrets.token_bytes(32).hex()
    deny = (login_password, luks_passphrase, manifest_key_hex, SYNTH_LOGIN_USER)

    ev = Evidence(deny)
    _EVIDENCE_HOLDER["ev"] = ev
    persistence_disk = os.path.join(root, "TestPersistenceDisk-001.qcow2")
    pkgs_iso = os.path.join(root, "pkgs.iso")
    system_a = os.path.join(root, "TestSystem-A.qcow2")
    serial_sock = os.path.join(root, "serial-a.sock")
    monitor_sock = os.path.join(root, "monitor-a.sock")

    if os.path.exists(system_a):
        os.unlink(system_a)
    subprocess.run(["qemu-img", "convert", "-O", "qcow2", "-f", "qcow2", BASE_IMAGE, system_a],
                    check=True, capture_output=True)

    if os.path.exists(persistence_disk):
        os.unlink(persistence_disk)
    subprocess.run(["qemu-img", "create", "-f", "qcow2", persistence_disk, "256M"],
                    check=True, capture_output=True)

    import tempfile
    seeddir = tempfile.mkdtemp()
    with open(os.path.join(seeddir, "meta-data"), "w") as f:
        f.write("instance-id: TestSystem-A-m5\nlocal-hostname: TestSystem-A\n")
    with open(os.path.join(seeddir, "user-data"), "w") as f:
        f.write(f"""#cloud-config
users:
  - name: {SYNTH_LOGIN_USER}
    sudo: ALL=(ALL) NOPASSWD:ALL
    lock_passwd: false
    plain_text_passwd: '{login_password}'
    shell: /bin/bash
chpasswd:
  expire: false
ssh_pwauth: false
package_update: false
package_upgrade: false
""")
    seed_a = os.path.join(root, "seed.iso")
    if os.path.exists(seed_a):
        os.unlink(seed_a)
    subprocess.run(["xorriso", "-as", "genisoimage", "-output", seed_a,
                     "-volid", "cidata", "-joliet", "-rock",
                     os.path.join(seeddir, "user-data"), os.path.join(seeddir, "meta-data")],
                    check=True, capture_output=True)

    proc = launch(root, system_a, persistence_disk, (seed_a, pkgs_iso), serial_sock, monitor_sock)
    con = console.SerialConsole(serial_sock, connect_timeout=30)
    try:
        wait_for_login_prompt(con, timeout=240)
        ev.record("boot_TestSystem-A", True, "login prompt reached")
        login(con, SYNTH_LOGIN_USER, login_password)
        ev.record("login", True, "logged in as synthetic test account")

        out = run_cmd(con,
                       'PKGDEV=$(sudo blkid -L pkgclosure) && sudo mkdir -p /mnt/pkgs && '
                       'sudo mount -o ro "$PKGDEV" /mnt/pkgs && cd /mnt/pkgs && '
                       'sudo dpkg -i *.deb; sudo dpkg -i *.deb; '
                       "dpkg-query -W -f='${Status}\\n' cryptsetup-bin dmsetup 2>&1",
                       "PKGDONE", timeout=90)
        ev.record("install_offline_packages", out.count("install ok installed") >= 2, out)

        out = run_cmd(con,
                       f"printf '%s' '{luks_passphrase}' > /tmp/luks.key && chmod 600 /tmp/luks.key && "
                       "wc -c < /tmp/luks.key && ls -la /tmp/luks.key",
                       "KEYFILEDONE", timeout=15)
        ev.record("keyfile_written_and_locked_down",
                   "KEYFILEDONE" in out and "-rw-------" in out, out)

        out = run_cmd(con,
                       "sudo cryptsetup luksFormat --type luks2 --batch-mode "
                       "--pbkdf-memory 65536 /dev/vdb /tmp/luks.key",
                       "LUKSFMTDONE", timeout=60)
        ev.record("luks_format", "LUKSFMTDONE" in out and "Failed" not in out, out)

        out = run_cmd(con, "sudo cryptsetup open --key-file /tmp/luks.key /dev/vdb testpersistence001",
                       "LUKSOPENDONE", timeout=60)
        ev.record("luks_open", "LUKSOPENDONE" in out, out)

        out = run_cmd(con,
                       "sudo mkfs.ext4 -q /dev/mapper/testpersistence001 && sudo mkdir -p /mnt/persistence "
                       "&& sudo mount /dev/mapper/testpersistence001 /mnt/persistence",
                       "EXT4DONE", timeout=30)
        ev.record("ext4_and_mount", "EXT4DONE" in out, out)

        # --- create the two synthetic application principals -----------------
        # No -N: each principal gets its own private group of the same name
        # (testapplication-a:testapplication-a), which the chown calls below rely on.
        out = run_cmd(con,
                       "sudo useradd -M -s /usr/sbin/nologin testapplication-a; "
                       "sudo useradd -M -s /usr/sbin/nologin testapplication-b; "
                       "id testapplication-a; id testapplication-b",
                       "USERSDONE", timeout=15)
        ev.record("create_application_principals",
                   "testapplication-a" in out and "testapplication-b" in out
                   and "gid=" in out and "no such user" not in out.lower(), out)

        # --- init manifest + ledger, and TestDocuments content, default-deny --
        assert send_script(con, INIT_SCRIPT, "/tmp/init_manifest.py")
        out = run_cmd(con, f"sudo python3 /tmp/init_manifest.py {manifest_key_hex}",
                       "INITDONE", timeout=20)
        ev.record("init_manifest_and_ledger", "INIT_WRITTEN" in out, out)

        out = run_cmd(con,
                       "sudo mkdir -p /mnt/persistence/collections/TestDocuments && "
                       "echo 'synthetic TestDocuments content for TestPerson-001' | "
                       "sudo tee /mnt/persistence/collections/TestDocuments/document.txt >/dev/null && "
                       "sudo chown -R root:root /mnt/persistence/collections/TestDocuments && "
                       "sudo chmod -R 700 /mnt/persistence/collections/TestDocuments",
                       "COLLECTIONDONE", timeout=15)
        ev.record("create_collection_default_deny", "COLLECTIONDONE" in out, out)

        # Per-application own state directories - never readable by the other app.
        out = run_cmd(con,
                       "sudo mkdir -p /mnt/persistence/app_state/TestApplication-A && "
                       "sudo mkdir -p /mnt/persistence/app_state/TestApplication-B && "
                       "echo 'TestApplication-A own state' | sudo tee "
                       "/mnt/persistence/app_state/TestApplication-A/state.txt >/dev/null && "
                       "sudo chown -R testapplication-a:testapplication-a /mnt/persistence/app_state/TestApplication-A && "
                       "sudo chmod -R 700 /mnt/persistence/app_state/TestApplication-A && "
                       "sudo chown -R testapplication-b:testapplication-b /mnt/persistence/app_state/TestApplication-B && "
                       "sudo chmod -R 700 /mnt/persistence/app_state/TestApplication-B",
                       "APPSTATEDONE", timeout=15)
        ev.record("acceptance_case3_app_install_and_state_write",
                   "APPSTATEDONE" in out and "chown:" not in out and "invalid group" not in out, out)

        # --- issue TestGrant-001: TestApplication-A -> TestDocuments, read -----
        assert send_script(con, GRANT_SCRIPT, "/tmp/grant.py")
        out = run_cmd(con,
                       f"sudo python3 /tmp/grant.py {manifest_key_hex} issue TestGrant-001 "
                       "TestPerson-001 TestApplication-A TestDocuments read",
                       "GRANTISSUEDONE", timeout=15)
        ev.record("grant_issued_in_ledger", "GRANT_ISSUE_DONE" in out, out)

        # Broker enforcement action for the grant: chown/chmod, a real DAC change.
        out = run_cmd(con,
                       "sudo chown -R testapplication-a:testapplication-a "
                       "/mnt/persistence/collections/TestDocuments && "
                       "sudo chmod -R 700 /mnt/persistence/collections/TestDocuments",
                       "ENFORCEISSUEDONE", timeout=15)
        ev.record("broker_enforces_grant_via_chown",
                   "ENFORCEISSUEDONE" in out and "chown:" not in out and "invalid group" not in out, out)

        # Acceptance case 3 (continued): the granted application can now read it.
        out = run_cmd(con,
                       "sudo -u testapplication-a cat /mnt/persistence/collections/TestDocuments/document.txt "
                       "&& echo READ_OK || echo READ_DENIED",
                       "AREADCHECK", timeout=15)
        ev.record("case3_grantee_can_read", "READ_OK" in out, out)

        # Acceptance case 7: isolation - TestApplication-B cannot read TestDocuments,
        # and cannot read TestApplication-A's own app-state either.
        out = run_cmd(con,
                       "sudo -u testapplication-b cat /mnt/persistence/collections/TestDocuments/document.txt "
                       "&& echo READ_OK || echo READ_DENIED",
                       "BREADCHECK1", timeout=15)
        ev.record("case7_non_grantee_cannot_read_collection", "READ_DENIED" in out and "READ_OK" not in out, out)

        out = run_cmd(con,
                       "sudo -u testapplication-b cat /mnt/persistence/app_state/TestApplication-A/state.txt "
                       "&& echo READ_OK || echo READ_DENIED",
                       "BREADCHECK2", timeout=15)
        ev.record("case7_isolation_of_app_state", "READ_DENIED" in out and "READ_OK" not in out, out)

        # No raw device or key access for either application principal.
        out = run_cmd(con,
                       "sudo -u testapplication-a cat /dev/vdb > /dev/null 2>&1 && echo RAW_OK || echo RAW_DENIED; "
                       "sudo -u testapplication-a cat /dev/mapper/testpersistence001 > /dev/null 2>&1 && echo MAP_OK || echo MAP_DENIED; "
                       "sudo -u testapplication-a cat /tmp/luks.key > /dev/null 2>&1 && echo KEY_OK || echo KEY_DENIED",
                       "RAWCHECK", timeout=15)
        ev.record("no_raw_device_or_key_access_for_application",
                   "RAW_DENIED" in out and "MAP_DENIED" in out and "KEY_DENIED" in out
                   and "RAW_OK" not in out and "MAP_OK" not in out and "KEY_OK" not in out,
                   out)

        # --- Acceptance case 8: revoke TestGrant-001 ---------------------------
        authorize("revoke_grant_TestGrant-001", True)
        out = run_cmd(con,
                       f"sudo python3 /tmp/grant.py {manifest_key_hex} revoke TestGrant-001 "
                       "TestPerson-001 TestApplication-A TestDocuments read",
                       "GRANTREVOKEDONE", timeout=15)
        ev.record("grant_revoked_in_ledger", "GRANT_REVOKE_DONE" in out, out)

        out = run_cmd(con,
                       "sudo chown -R root:root /mnt/persistence/collections/TestDocuments && "
                       "sudo chmod -R 700 /mnt/persistence/collections/TestDocuments",
                       "ENFORCEREVOKEDONE", timeout=15)
        ev.record("broker_enforces_revocation_via_chown",
                   "ENFORCEREVOKEDONE" in out and "chown:" not in out and "invalid group" not in out, out)

        out = run_cmd(con,
                       "sudo -u testapplication-a cat /mnt/persistence/collections/TestDocuments/document.txt "
                       "&& echo READ_OK || echo READ_DENIED",
                       "POSTREVOKECHECK", timeout=15)
        ev.record("case8_grantee_access_removed_after_revoke", "READ_DENIED" in out and "READ_OK" not in out, out)

        out = run_cmd(con, "sudo cat /mnt/persistence/collections/TestDocuments/document.txt",
                       "DATAINTACTCHECK", timeout=15)
        ev.record("case8_data_not_deleted_by_revocation",
                   "synthetic TestDocuments content" in out, out)

        # --- dump manifest + ledger for host-side verification -----------------
        # Wrapped in unique sentinels rather than sliced by brace/bracket
        # position: bash's own bracketed-paste toggle (\x1b[?2004l) contains a
        # literal "[" character, which a naive index("[") search can match
        # instead of the real JSON array's opening bracket.
        out = run_cmd(con, "echo JSONSTART; sudo cat /mnt/persistence/manifest.json; echo JSONEND",
                       "MANIFESTDUMP", timeout=15)
        manifest_text = out.split("JSONSTART", 1)[1].split("JSONEND", 1)[0]
        ev.record("manifest_dump", '"logical_identity"' in manifest_text, manifest_text)

        out = run_cmd(con, "echo JSONSTART; sudo cat /mnt/persistence/ledger.json; echo JSONEND",
                       "LEDGERDUMP", timeout=15)
        ledger_text = out.split("JSONSTART", 1)[1].split("JSONEND", 1)[0]
        ev.record("ledger_dump", '"store_created"' in ledger_text, ledger_text)

        try:
            manifest = json.loads(manifest_text)
            ledger = json.loads(ledger_text)

            grant = manifest["namespaces"]["grants"]["TestGrant-001"]
            grant_state_correct = grant["effective"] is False  # revoked, not deleted from the ledger record

            sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "baseline", "lib"))
            from testpersistence.manifest import TEST_MANIFEST_DOMAIN, LedgerEntry

            key = bytes.fromhex(manifest_key_hex)
            entries = [LedgerEntry(e["sequence"], e["event"], e["payload"], e["previous_mac"], e["mac"])
                       for e in ledger]
            prev = ""
            chain_ok = True
            for e in entries:
                if e.previous_mac != prev or not e.verify(key, TEST_MANIFEST_DOMAIN):
                    chain_ok = False
                    break
                prev = e.mac
            events = [e.event for e in entries]
            sequence_correct = events == ["store_created", "grant_issued", "grant_revoked"]

            ev.record("host_side_ledger_and_grant_state_verified",
                      grant_state_correct and chain_ok and sequence_correct,
                      f"grant_effective_after_revoke={grant['effective']} "
                      f"ledger_chain_verifies={chain_ok} event_sequence={events}")
        except Exception as exc:
            ev.record("host_side_ledger_and_grant_state_verified", False, f"verification error: {exc!r}")

        out = run_cmd(con,
                       "sudo umount /mnt/persistence && sudo cryptsetup close testpersistence001",
                       "CLEANUPDONE", timeout=20)
        ev.record("pre_shutdown_cleanup", "CLEANUPDONE" in out, out)

        clean_shutdown(con, proc, timeout=150)
        ev.record("clean_shutdown", True, "guest reported shutdown, process exited")
    finally:
        con.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except Exception:
                proc.kill()
        for p in (serial_sock, monitor_sock):
            if os.path.exists(p):
                os.unlink(p)

    ev.write(os.path.join(root, "evidence.json"))
    overall_ok = all(s["ok"] for s in ev.steps)
    print(f"\nOVERALL: {'PASS' if overall_ok else 'FAIL'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    try:
        _rc = main()
    except Exception as _exc:
        _ev = _EVIDENCE_HOLDER.get("ev")
        _safe_message = sanitized_failure_message(_exc, _ev)
        if _ev is not None:
            _ev.record("unhandled_exception", False, _safe_message)
            _ev.write(os.path.join(EXPERIMENT_ROOT, "evidence.json"))
        # See testpersistence_phaseB_vertical_slice.sanitized_failure_message's
        # docstring: the original exception is deliberately discarded here so
        # its unsanitized text can never reach the default excepthook.
        raise SystemExit(f"FAILED (sanitized): {_safe_message}") from None
    raise SystemExit(_rc)
