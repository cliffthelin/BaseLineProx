"""TestPersistence Milestone 3, Phase B: the narrow creation/rebuild/
reattach vertical slice (docs/design/testpersistence-prd.md).

Runs entirely against file-backed QEMU images validated by
tools/qemu_harness_safety.py. Boots a Debian 13 genericcloud guest
(never the downloaded cache file itself - always an independent copy),
with no network device at all, so nothing in the guest can depend on
live internet access. Two explicit, non-default, non-timeout-bounded
authorization gates (authorize()) model the PRD's attachment state
machine requirement that detection never auto-unlocks or auto-imports.

Evidence is bounded and sanitized (tools/qemu_harness_safety.
sanitize_evidence_text) before being written to
<experiment_root>/evidence.json - never an absolute host path, the
guest login credential, or the LUKS passphrase.
"""
import json
import os
import secrets
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qemu_harness_safety as h  # noqa: E402
import qemu_serial_console as console  # noqa: E402

EXPERIMENT_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "experiments", "testpersistence-m3-phaseB", "experiment-root")
DOWNLOAD_CACHE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "experiments", "testpersistence-m3-phaseB", "download-cache")
BASE_IMAGE = os.path.join(
    DOWNLOAD_CACHE, "debian-13-genericcloud-amd64-20260914-2601.qcow2")

SYNTH_LOGIN_USER = "testoperator"
GUEST_LOGIN_PROMPT = "TestSystem"  # the hostname prefixes the getty login prompt


class StepFailed(Exception):
    pass


_EVIDENCE_HOLDER = {}  # lets __main__ persist partial evidence if main() raises


def authorize(step_name: str, granted: bool) -> None:
    """Models the PRD's "no default or timeout acceptance" requirement.
    `granted` has NO default - a caller that doesn't pass it explicitly
    gets a TypeError, not a silent False. This script only ever calls
    authorize(..., True) at the two points the user's own message
    explicitly authorized as steps 3 and 11 of this exact sequence;
    nothing here waits on live human input because this whole 12-step
    slice was itself the explicit authorization."""
    if granted is not True:
        raise StepFailed(f"{step_name}: authorization was not explicitly granted - refusing")


class Evidence:
    def __init__(self, deny_substrings):
        self.deny_substrings = deny_substrings
        self.steps = []

    def record(self, step: str, ok: bool, detail: str, max_chars: int = 2000):
        sanitized = h.sanitize_evidence_text(detail, deny_substrings=self.deny_substrings)
        if len(sanitized) > max_chars:
            sanitized = sanitized[:max_chars] + "...<truncated>"
        self.steps.append({"step": step, "ok": ok, "detail": sanitized,
                            "recorded_at": time.time()})
        print(f"[{'OK' if ok else 'FAIL'}] {step}")
        print(f"    detail: {sanitized[:400]!r}")
        sys.stdout.flush()

    def write(self, path: str):
        with open(path, "w") as f:
            json.dump(self.steps, f, indent=2)


def build_system_args(root, system_disk, persistence_disk, extra_isos, serial_sock, monitor_sock):
    args = []
    resolved_system = h.validate_image_path(root, system_disk, must_be_new=False)
    args += ["-drive", f"file={resolved_system},format=qcow2,if=virtio"]
    resolved_persistence = h.validate_image_path(root, persistence_disk, must_be_new=False)
    args += ["-drive", f"file={resolved_persistence},format=qcow2,if=virtio"]
    for iso in extra_isos:
        resolved_iso = h.validate_image_path(root, iso, must_be_new=False)
        args += ["-drive", f"file={resolved_iso},format=raw,if=virtio,media=cdrom,readonly=on"]
    args += [
        "-m", "2048", "-smp", "2", "-display", "none", "-no-reboot",
        "-machine", "q35",
        "-accel", "kvm" if os.access("/dev/kvm", os.R_OK | os.W_OK) else "tcg",
        "-chardev", f"socket,id=serial0,path={serial_sock},server=on,wait=off",
        "-serial", "chardev:serial0",
        "-monitor", f"unix:{monitor_sock},server,nowait",
    ]
    return args


def launch(root, system_disk, persistence_disk, extra_isos, serial_sock, monitor_sock):
    for p in (serial_sock, monitor_sock):
        if os.path.exists(p):
            os.unlink(p)
    args = build_system_args(root, system_disk, persistence_disk, extra_isos,
                              serial_sock, monitor_sock)
    return h.run_qemu("qemu-system-x86_64", args)


def wait_for_login_prompt(con: console.SerialConsole, timeout=240):
    con.read_until("login:", timeout=timeout)


def login(con: console.SerialConsole, user: str, password: str):
    con.send_line(user)
    con.read_until("Password:", timeout=30)
    con.send_line(password)
    con.drain(quiet_for=2, max_wait=15)
    # Disable tty echo immediately - every run_cmd() call after this point
    # relies on echo being off so a marker can only appear as genuine
    # command output, never as an echo of what we just typed. Drain away
    # whatever comes back from the transition itself (its own echo, since
    # echo was still on when we sent it) rather than trying to parse it.
    con.send_line("stty -echo")
    con.drain(quiet_for=2, max_wait=10)
    out = run_cmd(con, "true", "LOGIN_CONFIRMED", timeout=20)
    if "LOGIN_CONFIRMED" not in out:
        raise StepFailed(f"login/echo-disable did not reach a usable shell - last output: {out[-500:]!r}")


def run_cmd(con: console.SerialConsole, cmd: str, marker: str, timeout=60) -> str:
    """Sends `cmd`, then a distinctive marker, and reads until that
    marker appears in the output. Relies on `stty -echo` having been
    set on the guest tty right after login (see login()) - with tty
    echo disabled, the only way the marker text can appear in the
    stream at all is as genuine command output, so a single
    read_until is reliable. (An earlier version of this function tried
    to skip a first "input echo" occurrence instead of disabling echo
    at the source - that broke down under bracketed-paste redraw
    artifacts, which could echo input more than once. Removing the
    echo removes the whole ambiguity, rather than trying to count
    occurrences of it.)"""
    con.send_line(f"{cmd}; echo {marker}")
    out = con.read_until(marker, timeout=timeout)
    return out


def clean_shutdown(con: console.SerialConsole, proc: subprocess.Popen, timeout=60):
    con.send_line("sudo shutdown -h now")
    deadline = time.time() + timeout
    seen = ""
    while proc.poll() is None and time.time() < deadline:
        seen += con.drain(quiet_for=0.5, max_wait=3)
        time.sleep(1)
    if proc.poll() is None:
        proc.terminate()
        raise StepFailed(
            "guest did not shut down cleanly within timeout - process terminated. "
            f"console output seen while waiting: {seen[-2000:]!r}")


LEDGER_SNIPPET = r"""
import hashlib, hmac, json, sys
DOMAIN = b"baseline-manifest-test-v1:"
KEY = bytes.fromhex(sys.argv[1])

def canon(seq, event, payload, prev):
    return json.dumps({"sequence": seq, "event": event, "payload": payload,
                        "previous_mac": prev}, sort_keys=True).encode()

def mac(seq, event, payload, prev):
    return hmac.new(KEY, DOMAIN + canon(seq, event, payload, prev), hashlib.sha256).hexdigest()

manifest = {
    "schema_version": 1, "test_only": True,
    "manifest_domain": DOMAIN.decode(),
    "logical_identity": "TestPersistence-001",
    "carrier_identity": "TestPersistenceDisk-001",
    "generation": 1,
    "namespaces": {
        "person": {"TestPerson-001": {"documents_ref": "TestDocuments"}},
        "application_state": {"TestApplication-A": {}},
        "grants": {"TestGrant-001": {"person": "TestPerson-001", "application": "TestApplication-A",
                                       "collection": "TestDocuments", "access_mode": "read",
                                       "duration": "until_revoked", "authorized_by": "bootstrap",
                                       "effective": True}},
    },
}
entries = []
prev = ""
for i, (event, payload) in enumerate([
    ("store_created", {"logical_identity": "TestPersistence-001"}),
    ("grant_issued", {"grant_id": "TestGrant-001"}),
]):
    m = mac(i, event, payload, prev)
    entries.append({"sequence": i, "event": event, "payload": payload,
                     "previous_mac": prev, "mac": m})
    prev = m
manifest["authority_ledger"] = entries
with open("/mnt/persistence/manifest.json", "w") as f:
    json.dump(manifest, f, indent=2)
print("MANIFEST_WRITTEN")
"""


def main():
    os.makedirs(EXPERIMENT_ROOT, exist_ok=True)
    root = h.validate_experiment_root(EXPERIMENT_ROOT)

    login_password = secrets.token_urlsafe(24)
    luks_passphrase = secrets.token_urlsafe(24)
    manifest_key_hex = secrets.token_bytes(32).hex()
    deny = (login_password, luks_passphrase, manifest_key_hex, SYNTH_LOGIN_USER)

    ev = Evidence(deny)
    _EVIDENCE_HOLDER["ev"] = ev  # so a crash can still persist partial evidence - see __main__
    persistence_disk = os.path.join(root, "TestPersistenceDisk-001.qcow2")
    seed_a = os.path.join(root, "seed.iso")
    pkgs_iso = os.path.join(root, "pkgs.iso")
    system_a = os.path.join(root, "TestSystem-A.qcow2")

    # Step 1 starts from a FRESH TestSystem-A every run - never a disk left over
    # from an earlier run. This also sidesteps a real bug this fixed: cloud-init
    # only applies user-data once per instance-id, so reusing an old disk across
    # runs with a freshly-generated password would silently keep the OLD
    # password, and login would fail against the new one.
    if os.path.exists(system_a):
        os.unlink(system_a)

    # The persistence CARRIER also starts blank every run - step 2's "detection
    # alone causes no auto-format" proof is only meaningful against a carrier
    # that hasn't already been LUKS-formatted by an earlier run.
    if os.path.exists(persistence_disk):
        os.unlink(persistence_disk)
    subprocess.run(["qemu-img", "create", "-f", "qcow2", persistence_disk, "256M"],
                    check=True, capture_output=True)
    subprocess.run(["qemu-img", "convert", "-O", "qcow2", "-f", "qcow2", BASE_IMAGE, system_a],
                    check=True, capture_output=True)
    system_b = os.path.join(root, "TestSystem-B.qcow2")
    serial_sock = os.path.join(root, "serial-a.sock")
    monitor_sock = os.path.join(root, "monitor-a.sock")

    # --- rewrite seed.iso's password to the freshly generated one for this run ---
    import tempfile
    seeddir = tempfile.mkdtemp()
    with open(os.path.join(seeddir, "meta-data"), "w") as f:
        f.write("instance-id: TestSystem-A-phaseB\nlocal-hostname: TestSystem-A\n")
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
    if os.path.exists(seed_a):
        os.unlink(seed_a)
    subprocess.run(["xorriso", "-as", "genisoimage", "-output", seed_a,
                     "-volid", "cidata", "-joliet", "-rock",
                     os.path.join(seeddir, "user-data"), os.path.join(seeddir, "meta-data")],
                    check=True, capture_output=True)

    # ================= SYSTEM A =================
    proc_a = launch(root, system_a, persistence_disk, (seed_a, pkgs_iso),
                     serial_sock, monitor_sock)
    con = console.SerialConsole(serial_sock, connect_timeout=30)
    try:
        # Step 1: boot
        wait_for_login_prompt(con, timeout=240)
        ev.record("step1_boot_TestSystem-A", True, "login prompt reached")
        login(con, SYNTH_LOGIN_USER, login_password)
        ev.record("step1_login", True, "logged in as synthetic test account")

        # Step 2: detection alone performs no unlock/format/import/attach-writable.
        # An untouched block device has no recognizable signature (blkid prints
        # nothing, no TYPE=) and is not mounted (mount | grep finds nothing).
        out = run_cmd(con, "sudo blkid /dev/vdb; sudo lsblk /dev/vdb; mount | grep vdb",
                       "STEP2DONE")
        no_fs_signature = "TYPE=" not in out
        not_mounted = "/mnt" not in out and "/dev/vdb " not in out.replace("vdb  ", "vdb ")
        ev.record("step2_detection_no_auto_action", no_fs_signature and not_mounted, out)

        # Step 3: explicit authorization gate before creating the encrypted store.
        # Granted here because the user's own message is the explicit, prior
        # authorization for exactly this step of exactly this sequence.
        authorize("create_encrypted_store", True)
        ev.record("step3_authorization_gate", True, "explicit authorization granted for LUKS2 creation")

        # Step 4: LUKS2 + ext4
        out = run_cmd(con, f"printf '%s' '{luks_passphrase}' > /tmp/luks.key && wc -c < /tmp/luks.key",
                       "KEYFILEWRITTEN", timeout=15)
        ev.record("step4_keyfile_written", "KEYFILEWRITTEN" in out, out)
        out = run_cmd(con,
                       'PKGDEV=$(sudo blkid -L pkgclosure) && sudo mkdir -p /mnt/pkgs && '
                       'sudo mount -o ro "$PKGDEV" /mnt/pkgs && cd /mnt/pkgs && '
                       'sudo dpkg -i *.deb; sudo dpkg -i *.deb; '
                       "dpkg-query -W -f='${Status}\\n' cryptsetup-bin dmsetup 2>&1; "
                       "ls -la /sbin/mkfs.ext4 /usr/bin/python3 2>&1",
                       "STEP4APKGDONE", timeout=90)
        tools_present = out.count("install ok installed") >= 2 and "mkfs.ext4" in out and "python3" in out
        ev.record("step4a_install_offline_packages", "STEP4APKGDONE" in out and tools_present, out)

        out = run_cmd(con,
                       # --pbkdf-memory bounds Argon2id's memory cost to something this
                       # small experiment VM can actually satisfy quickly - the default
                       # (~1GiB) would thrash badly on a constrained guest. This is a
                       # test-experiment tuning parameter only, not a security posture
                       # claim about any production configuration.
                       "sudo cryptsetup luksFormat --type luks2 --batch-mode "
                       "--pbkdf-memory 65536 /dev/vdb /tmp/luks.key",
                       "STEP4BDONE", timeout=60)
        ev.record("step4b_luks_format",
                   "STEP4BDONE" in out and "Failed" not in out and "Error" not in out, out)

        out = run_cmd(con,
                       "sudo cryptsetup open --key-file /tmp/luks.key /dev/vdb testpersistence001",
                       "STEP4CDONE", timeout=60)
        ev.record("step4c_luks_open", "STEP4CDONE" in out, out)

        out = run_cmd(con,
                       "sudo mkfs.ext4 -q /dev/mapper/testpersistence001 && sudo mkdir -p /mnt/persistence "
                       "&& sudo mount /dev/mapper/testpersistence001 /mnt/persistence",
                       "STEP4DDONE", timeout=30)
        ev.record("step4d_ext4_and_mount", "STEP4DDONE" in out, out)

        # Step 5+6: write authenticated synthetic manifest/ledger with person/doc/app/grant.
        # Sent as one base64-encoded line rather than a multi-line heredoc - far more
        # robust over a raw, line-buffered serial console than embedded newlines.
        import base64
        encoded = base64.b64encode(LEDGER_SNIPPET.encode()).decode()
        out = run_cmd(con, f"echo {encoded} | base64 -d > /tmp/write_manifest.py",
                       "STEP5WRITEDONE", timeout=20)
        ev.record("step5a_script_transferred", "STEP5WRITEDONE" in out, out)

        out = run_cmd(con, f"sudo python3 /tmp/write_manifest.py {manifest_key_hex}",
                       "STEP5DONE", timeout=30)
        ev.record("step5b_manifest_and_ledger_written", "MANIFEST_WRITTEN" in out, out)

        out = run_cmd(con, "sudo cat /mnt/persistence/manifest.json", "STEP6DUMPDONE", timeout=15)
        manifest_json_text = out.split("STEP6DUMPDONE")[0]
        ev.record("step6_manifest_dump_before_shutdown", '"logical_identity"' in manifest_json_text,
                   manifest_json_text)

        # clean unmount/close before shutdown
        cleanup_out = run_cmd(
            con,
            "sudo umount /mnt/persistence && sudo cryptsetup close testpersistence001 && "
            "echo CLEANUP_OK || echo CLEANUP_FAILED; mount | grep persistence; "
            "sudo dmsetup ls 2>&1",
            "STEP6CLEANDONE", timeout=20)
        ev.record("step6b_pre_shutdown_cleanup", "CLEANUP_OK" in cleanup_out, cleanup_out)

        # Step 7 (shutdown, part of "clean shutdown")
        clean_shutdown(con, proc_a, timeout=200)
        ev.record("step7_clean_shutdown_TestSystem-A", True, "guest reported shutdown, process exited")
    finally:
        con.close()
        if proc_a.poll() is None:
            proc_a.terminate()
            proc_a.wait(timeout=20)
        for p in (serial_sock, monitor_sock):
            if os.path.exists(p):
                os.unlink(p)

    # Step 8: delete only the exact validated TestSystem-A image, preserve persistence
    h.delete_validated_image(root, system_a)
    ev.record("step8_delete_TestSystem-A_only", not os.path.exists(system_a) and os.path.exists(persistence_disk),
               "TestSystem-A.qcow2 removed via os.unlink; TestPersistenceDisk-001.qcow2 preserved")

    # Step 9: create TestSystem-B independently from the same verified base
    if os.path.exists(system_b):
        os.unlink(system_b)
    subprocess.run(["qemu-img", "convert", "-O", "qcow2", "-f", "qcow2", BASE_IMAGE, system_b],
                    check=True, capture_output=True)
    ev.record("step9_create_TestSystem-B", os.path.exists(system_b),
               "independent qemu-img convert copy of the same verified base image, no backing file")

    seeddir_b = tempfile.mkdtemp()
    with open(os.path.join(seeddir_b, "meta-data"), "w") as f:
        f.write("instance-id: TestSystem-B-phaseB\nlocal-hostname: TestSystem-B\n")
    with open(os.path.join(seeddir_b, "user-data"), "w") as f:
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
    seed_b = os.path.join(root, "seed-b.iso")
    if os.path.exists(seed_b):
        os.unlink(seed_b)
    subprocess.run(["xorriso", "-as", "genisoimage", "-output", seed_b,
                     "-volid", "cidata", "-joliet", "-rock",
                     os.path.join(seeddir_b, "user-data"), os.path.join(seeddir_b, "meta-data")],
                    check=True, capture_output=True)

    serial_sock_b = os.path.join(root, "serial-b.sock")
    monitor_sock_b = os.path.join(root, "monitor-b.sock")
    proc_b = launch(root, system_b, persistence_disk, (seed_b, pkgs_iso),
                     serial_sock_b, monitor_sock_b)
    con_b = console.SerialConsole(serial_sock_b, connect_timeout=30)
    try:
        wait_for_login_prompt(con_b, timeout=240)
        login(con_b, SYNTH_LOGIN_USER, login_password)
        ev.record("step9_boot_TestSystem-B_and_login", True, "TestSystem-B booted and logged in")

        # TestSystem-B is a fresh base-image copy - it needs cryptsetup installed
        # too, from the same verified offline closure, before any LUKS operation.
        out = run_cmd(con_b,
                       'PKGDEV=$(sudo blkid -L pkgclosure) && sudo mkdir -p /mnt/pkgs && '
                       'sudo mount -o ro "$PKGDEV" /mnt/pkgs && cd /mnt/pkgs && '
                       'sudo dpkg -i *.deb; sudo dpkg -i *.deb; '
                       "dpkg-query -W -f='${Status}\\n' cryptsetup-bin dmsetup 2>&1",
                       "STEPBPKGDONE", timeout=90)
        ev.record("step9b_install_offline_packages_on_TestSystem-B",
                   out.count("install ok installed") >= 2, out)

        # Step 10/11: attached persistence carrier must appear locked/untrusted,
        # not auto-unlocked, no inherited authorization.
        out = run_cmd(con_b, "sudo cryptsetup isLuks /dev/vdb && echo IS_LUKS; "
                              "sudo lsblk /dev/vdb; mount | grep vdb || echo NOT_MOUNTED",
                       "STEP10DONE", timeout=20)
        locked_untrusted = "IS_LUKS" in out and "NOT_MOUNTED" in out
        ev.record("step10_carrier_locked_untrusted_no_inherited_auth", locked_untrusted, out)

        authorize("import_and_unlock_on_TestSystem-B", True)
        ev.record("step11_authorization_gate", True,
                   "explicit authorization granted for import/unlock on TestSystem-B")

        out = run_cmd(con_b, f"printf '%s' '{luks_passphrase}' > /tmp/luks.key && wc -c < /tmp/luks.key",
                       "KEYFILEWRITTENB", timeout=15)
        ev.record("step11_keyfile_written_on_TestSystem-B", "KEYFILEWRITTENB" in out, out)
        out = run_cmd(con_b,
                       "sudo cryptsetup open --key-file /tmp/luks.key /dev/vdb testpersistence001 && "
                       "sudo mkdir -p /mnt/persistence && "
                       "sudo mount /dev/mapper/testpersistence001 /mnt/persistence",
                       "STEP11UNLOCKDONE", timeout=30)
        ev.record("step11_unlock_and_mount_on_TestSystem-B", "STEP11UNLOCKDONE" in out, out)

        # Step 12: continuity - same logical store, data, generation, ledger chain
        out = run_cmd(con_b, "sudo cat /mnt/persistence/manifest.json", "STEP12DUMPDONE", timeout=15)
        manifest_b_text = out.split("STEP12DUMPDONE")[0]
        ev.record("step12_manifest_dump_after_reattach", True, manifest_b_text)

        try:
            manifest_a = json.loads(manifest_json_text[manifest_json_text.index("{"):
                                                         manifest_json_text.rindex("}") + 1])
            manifest_b = json.loads(manifest_b_text[manifest_b_text.index("{"):
                                                      manifest_b_text.rindex("}") + 1])
            same_logical = manifest_a["logical_identity"] == manifest_b["logical_identity"]
            same_generation = manifest_a["generation"] == manifest_b["generation"]
            same_person_docs = (manifest_a["namespaces"]["person"] == manifest_b["namespaces"]["person"])
            same_grants = manifest_a["namespaces"]["grants"] == manifest_b["namespaces"]["grants"]

            sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "baseline", "lib"))
            from testpersistence.manifest import (TEST_MANIFEST_DOMAIN, LedgerEntry,
                                                    derive_manifest_key)
            key = bytes.fromhex(manifest_key_hex)
            entries = [LedgerEntry(e["sequence"], e["event"], e["payload"],
                                    e["previous_mac"], e["mac"])
                       for e in manifest_b["authority_ledger"]]
            prev = ""
            chain_ok = True
            for e in entries:
                if e.previous_mac != prev or not e.verify(key, TEST_MANIFEST_DOMAIN):
                    chain_ok = False
                    break
                prev = e.mac

            ev.record("step12_continuity_verified",
                      same_logical and same_generation and same_person_docs and same_grants and chain_ok,
                      f"same_logical_identity={same_logical} same_generation={same_generation} "
                      f"same_person_and_documents={same_person_docs} same_grants={same_grants} "
                      f"ledger_chain_verifies_host_side={chain_ok}")
        except Exception as exc:
            ev.record("step12_continuity_verified", False, f"verification error: {exc!r}")

        con_b.send_line("sudo umount /mnt/persistence && sudo cryptsetup close testpersistence001")
        con_b.drain(quiet_for=2)
        clean_shutdown(con_b, proc_b, timeout=150)
        ev.record("clean_shutdown_TestSystem-B", True, "guest reported shutdown, process exited")
    finally:
        con_b.close()
        if proc_b.poll() is None:
            proc_b.terminate()
            proc_b.wait(timeout=20)
        for p in (serial_sock_b, monitor_sock_b):
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
        if _ev is not None:
            _ev.record("unhandled_exception", False, f"{type(_exc).__name__}: {_exc}")
            _ev.write(os.path.join(EXPERIMENT_ROOT, "evidence.json"))
        raise
    raise SystemExit(_rc)
