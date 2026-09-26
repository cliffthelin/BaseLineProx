"""TestPersistence Milestone 6: the eight failure modes (docs/design/
testpersistence-prd.md §13) exercised for real against the QEMU
harness, not just unit-tested (baseline/lib/testpersistence/
failures.py already covers these as pure-code Outcome objects -
Milestone 2 - this module proves the underlying OS-level *signals*
those outcomes are built on are genuinely observable in a live guest).

Three boots, reusing Phase B's proven helpers:

Boot A (missing) - system disk only, no persistence disk attached at
all - /dev/vdb simply doesn't exist. Quick, no package install needed.

Boot B (locked, unknown, corrupted, read-only, full, newer-schema) -
system + persistence disk (vdb) + a second, permanently-blank disk
(vdc, never formatted by anything in this script) attached together.

Boot C (cloned) - after Boot B shuts down, the persistence disk is
byte-copied (qemu-img convert, an independent copy - never a backing
file) to a second image; both are attached together and `blkid`
confirms they report the identical LUKS UUID. This models the PRD's
scoped claim precisely: simultaneous-attachment cloning IS reliably
observable this way; a clone used separately and never simultaneously
observed is explicitly NOT claimed detectable anywhere in this module,
matching docs/design/decision-records/28's scope statement.
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
    Evidence, StepFailed, clean_shutdown, launch, login, run_cmd,
    sanitized_failure_message, wait_for_login_prompt, _EVIDENCE_HOLDER,
)

EXPERIMENT_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "experiments", "testpersistence-m6-failures", "experiment-root")
DOWNLOAD_CACHE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "experiments", "testpersistence-m6-failures", "download-cache")
BASE_IMAGE = os.path.join(
    DOWNLOAD_CACHE, "debian-13-genericcloud-amd64-20260914-2601.qcow2")

SYNTH_LOGIN_USER = "testoperator"

NEWER_SCHEMA_SCRIPT = r"""
import json
manifest = {
    "schema_version": 99, "test_only": True,
    "manifest_domain": "baseline-manifest-test-v1:",
    "logical_identity": "TestPersistence-001", "carrier_identity": "TestPersistenceDisk-001",
    "generation": 1, "namespaces": {},
}
with open("/mnt/persistence/newer_schema_test.json", "w") as f:
    json.dump(manifest, f)
print("NEWER_SCHEMA_WRITTEN")
"""


def _make_seed(root, name, login_password):
    import tempfile
    seeddir = tempfile.mkdtemp()
    with open(os.path.join(seeddir, "meta-data"), "w") as f:
        f.write(f"instance-id: {name}-m6\nlocal-hostname: TestSystem-A\n")
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
    seed_path = os.path.join(root, f"seed-{name}.iso")
    if os.path.exists(seed_path):
        os.unlink(seed_path)
    subprocess.run(["xorriso", "-as", "genisoimage", "-output", seed_path,
                     "-volid", "cidata", "-joliet", "-rock",
                     os.path.join(seeddir, "user-data"), os.path.join(seeddir, "meta-data")],
                    check=True, capture_output=True)
    return seed_path


def _fresh_system_disk(root, name):
    path = os.path.join(root, f"{name}.qcow2")
    if os.path.exists(path):
        os.unlink(path)
    subprocess.run(["qemu-img", "convert", "-O", "qcow2", "-f", "qcow2", BASE_IMAGE, path],
                    check=True, capture_output=True)
    return path


def main():
    os.makedirs(EXPERIMENT_ROOT, exist_ok=True)
    root = h.validate_experiment_root(EXPERIMENT_ROOT)

    login_password = secrets.token_urlsafe(24)
    luks_passphrase = secrets.token_urlsafe(24)
    deny = (login_password, luks_passphrase, SYNTH_LOGIN_USER)

    ev = Evidence(deny)
    _EVIDENCE_HOLDER["ev"] = ev
    pkgs_iso = os.path.join(root, "pkgs.iso")
    persistence_disk = os.path.join(root, "TestPersistenceDisk-001.qcow2")
    unknown_disk = os.path.join(root, "unknown-disk.qcow2")
    clone_disk = os.path.join(root, "clone-disk.qcow2")

    for p in (persistence_disk, unknown_disk, clone_disk):
        if os.path.exists(p):
            os.unlink(p)
    subprocess.run(["qemu-img", "create", "-f", "qcow2", persistence_disk, "256M"],
                    check=True, capture_output=True)
    subprocess.run(["qemu-img", "create", "-f", "qcow2", unknown_disk, "64M"],
                    check=True, capture_output=True)

    # ===================== Boot A: missing =====================
    # The seed ISO is attached via the legacy IDE/SATA -cdrom path here,
    # deliberately NOT the shared virtio-cdrom mechanism build_system_args
    # uses elsewhere - a virtio cdrom drive also consumes a /dev/vdX letter,
    # which would make /dev/vdb "exist" (as the cdrom) even with no
    # persistence disk attached, defeating this exact test's premise.
    system_a = _fresh_system_disk(root, "TestSystem-A-missing")
    seed_a = _make_seed(root, "missing", login_password)
    serial_a = os.path.join(root, "serial-a.sock")
    monitor_a = os.path.join(root, "monitor-a.sock")
    for p in (serial_a, monitor_a):
        if os.path.exists(p):
            os.unlink(p)
    resolved_system_a = h.validate_image_path(root, system_a, must_be_new=False)
    resolved_seed_a = h.validate_image_path(root, seed_a, must_be_new=False)
    args_a = [
        "-drive", f"file={resolved_system_a},format=qcow2,if=virtio",
        "-cdrom", resolved_seed_a,
        "-m", "2048", "-smp", "2", "-display", "none", "-no-reboot", "-machine", "q35",
        "-accel", "kvm" if os.access("/dev/kvm", os.R_OK | os.W_OK) else "tcg",
        "-chardev", f"socket,id=serial0,path={serial_a},server=on,wait=off",
        "-serial", "chardev:serial0",
        "-monitor", f"unix:{monitor_a},server,nowait",
    ]
    proc = h.run_qemu("qemu-system-x86_64", args_a)
    con = console.SerialConsole(serial_a, connect_timeout=30)
    try:
        wait_for_login_prompt(con, timeout=240)
        login(con, SYNTH_LOGIN_USER, login_password)
        ev.record("bootA_login", True, "TestSystem-A booted with no persistence disk attached")

        out = run_cmd(con, "ls /dev/vdb 2>&1; ls /dev/vd* 2>&1", "MISSINGCHECK", timeout=15)
        ev.record("failure_missing_device_absent",
                   "No such file" in out and "/dev/vda" in out, out)

        clean_shutdown(con, proc, timeout=120)
        ev.record("bootA_clean_shutdown", True, "guest exited")
    finally:
        con.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except Exception:
                proc.kill()
        for p in (serial_a, monitor_a):
            if os.path.exists(p):
                os.unlink(p)
    h.delete_validated_image(root, system_a)

    # ===================== Boot B: the main matrix =====================
    system_b = _fresh_system_disk(root, "TestSystem-A-matrix")
    seed_b = _make_seed(root, "matrix", login_password)
    serial_b = os.path.join(root, "serial-b.sock")
    monitor_b = os.path.join(root, "monitor-b.sock")
    proc = launch(root, system_b, persistence_disk, (seed_b, pkgs_iso), serial_b, monitor_b,
                  extra_disks=(unknown_disk,))
    con = console.SerialConsole(serial_b, connect_timeout=30)
    try:
        wait_for_login_prompt(con, timeout=240)
        login(con, SYNTH_LOGIN_USER, login_password)
        ev.record("bootB_login", True, "TestSystem-A booted with persistence + unknown disks attached")

        # --- unknown: vdc was never formatted by anything, ever -----------
        out = run_cmd(con, "sudo blkid /dev/vdc; echo BLKIDRC=$?", "UNKNOWNCHECK", timeout=15)
        ev.record("failure_unknown_no_signature", "TYPE=" not in out, out)

        # --- install offline packages, then LUKS format+open+ext4+mount ---
        out = run_cmd(con,
                       'PKGDEV=$(sudo blkid -L pkgclosure) && sudo mkdir -p /mnt/pkgs && '
                       'sudo mount -o ro "$PKGDEV" /mnt/pkgs && cd /mnt/pkgs && '
                       'sudo dpkg -i *.deb; sudo dpkg -i *.deb; '
                       "dpkg-query -W -f='${Status}\\n' cryptsetup-bin dmsetup 2>&1",
                       "PKGDONE", timeout=90)
        ev.record("install_offline_packages", out.count("install ok installed") >= 2, out)

        out = run_cmd(con, f"printf '%s' '{luks_passphrase}' > /tmp/luks.key && chmod 600 /tmp/luks.key",
                       "KEYDONE", timeout=15)
        ev.record("keyfile_written", "KEYDONE" in out, out)

        out = run_cmd(con,
                       "sudo cryptsetup luksFormat --type luks2 --batch-mode "
                       "--pbkdf-memory 65536 /dev/vdb /tmp/luks.key",
                       "LUKSFMTDONE", timeout=60)
        ev.record("luks_format", "LUKSFMTDONE" in out and "Failed" not in out, out)

        # --- locked: formatted but not yet opened -------------------------
        out = run_cmd(con, "sudo cryptsetup isLuks /dev/vdb && echo IS_LUKS; "
                            "mount | grep vdb || echo NOT_MOUNTED", "LOCKEDCHECK", timeout=15)
        ev.record("failure_locked_not_yet_opened", "IS_LUKS" in out and "NOT_MOUNTED" in out, out)

        out = run_cmd(con, "sudo cryptsetup open --key-file /tmp/luks.key /dev/vdb testpersistence001",
                       "LUKSOPENDONE", timeout=60)
        ev.record("luks_open", "LUKSOPENDONE" in out, out)

        out = run_cmd(con,
                       "sudo mkfs.ext4 -q /dev/mapper/testpersistence001 && sudo mkdir -p /mnt/persistence "
                       "&& sudo mount /dev/mapper/testpersistence001 /mnt/persistence",
                       "EXT4DONE", timeout=30)
        ev.record("ext4_and_mount", "EXT4DONE" in out, out)

        out = run_cmd(con, "echo 'synthetic manifest content' | sudo tee /mnt/persistence/manifest.json "
                            ">/dev/null && sudo cat /mnt/persistence/manifest.json", "MANIFESTWRITTEN", timeout=15)
        ev.record("baseline_manifest_written", "synthetic manifest content" in out, out)

        # --- corrupted: a colocated copy, deliberately corrupted ----------
        out = run_cmd(con,
                       "sudo cp /mnt/persistence/manifest.json /mnt/persistence/corrupt_test.json && "
                       "sudo dd if=/dev/urandom of=/mnt/persistence/corrupt_test.json bs=8 count=1 "
                       "conv=notrunc status=none && "
                       "python3 -c \"import json; json.load(open('/mnt/persistence/corrupt_test.json'))\" "
                       "2>&1; echo RC=$?",
                       "CORRUPTCHECK", timeout=15)
        ev.record("failure_corrupted_detected_not_silently_accepted",
                   "RC=0" not in out and ("JSONDecodeError" in out or "Error" in out), out)
        run_cmd(con, "sudo rm -f /mnt/persistence/corrupt_test.json", "CORRUPTCLEANDONE", timeout=10)

        # --- newer-schema: write, dump, verify with the REAL manifest module ---
        encoded = base64.b64encode(NEWER_SCHEMA_SCRIPT.encode()).decode()
        run_cmd(con, f"echo {encoded} | base64 -d > /tmp/newer_schema.py", "NSXFERDONE", timeout=15)
        out = run_cmd(con, "sudo python3 /tmp/newer_schema.py", "NSWRITEDONE", timeout=15)
        ev.record("newer_schema_manifest_written", "NEWER_SCHEMA_WRITTEN" in out, out)

        out = run_cmd(con, "echo JSONSTART; sudo cat /mnt/persistence/newer_schema_test.json; echo JSONEND",
                       "NSDUMPDONE", timeout=15)
        ns_text = out.split("JSONSTART", 1)[1].split("JSONEND", 1)[0]
        try:
            ns_manifest = json.loads(ns_text)
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "baseline", "lib"))
            from testpersistence.manifest import SchemaVersionError, check_schema_version
            try:
                check_schema_version(ns_manifest["schema_version"], reader_supported_version=1)
                ev.record("failure_newer_schema_refused_by_real_module", False,
                          "check_schema_version did not raise - this must never happen")
            except SchemaVersionError as exc:
                ev.record("failure_newer_schema_refused_by_real_module", True,
                           f"correctly refused: {exc}")
        except Exception as exc:
            ev.record("failure_newer_schema_refused_by_real_module", False, f"error: {exc!r}")

        # --- read-only: remount ro, attempt a write, confirm refusal -------
        out = run_cmd(con, "sudo mount -o remount,ro /mnt/persistence && "
                            "(sudo touch /mnt/persistence/should_fail.txt 2>&1; echo RC=$?)",
                       "ROCHECK", timeout=15)
        ev.record("failure_read_only_write_refused",
                   "Read-only file system" in out and "RC=0" not in out, out)
        run_cmd(con, "sudo mount -o remount,rw /mnt/persistence", "RWRESTOREDONE", timeout=15)

        # --- full: fill the filesystem, confirm refusal without corrupting existing data --
        # No `| tail` here: dd's stderr is only a few lines, and an earlier
        # version of this check piped through `tail -3`, which cut away the
        # actual "No space left on device" line and left only the trailing
        # summary stats - the real behavior was correct (dd stopped early,
        # at 215 of the requested 1000 blocks), only the check itself was
        # wrong to rely on truncated output.
        out = run_cmd(con,
                       "sudo dd if=/dev/zero of=/mnt/persistence/filler bs=1M "
                       "count=1000 conv=notrunc 2>&1; "
                       "sudo cat /mnt/persistence/manifest.json",
                       "FULLCHECK", timeout=60)
        ev.record("failure_full_write_refused_data_intact",
                   ("No space left" in out or "No space" in out) and "synthetic manifest content" in out,
                   out)
        run_cmd(con, "sudo rm -f /mnt/persistence/filler", "FULLCLEANDONE", timeout=30)

        # --- cleanup -----------------------------------------------------
        out = run_cmd(con, "sudo umount /mnt/persistence && sudo cryptsetup close testpersistence001",
                       "CLEANUPDONE", timeout=20)
        ev.record("bootB_pre_shutdown_cleanup", "CLEANUPDONE" in out, out)

        clean_shutdown(con, proc, timeout=150)
        ev.record("bootB_clean_shutdown", True, "guest exited")
    finally:
        con.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except Exception:
                proc.kill()
        for p in (serial_b, monitor_b):
            if os.path.exists(p):
                os.unlink(p)
    h.delete_validated_image(root, system_b)

    # ===================== Boot C: cloned (simultaneous attachment) =====================
    subprocess.run(["qemu-img", "convert", "-O", "qcow2", "-f", "qcow2", persistence_disk, clone_disk],
                    check=True, capture_output=True)
    ev.record("clone_disk_created", os.path.exists(clone_disk),
               "independent qemu-img convert copy of the now-LUKS-formatted persistence disk")

    system_c = _fresh_system_disk(root, "TestSystem-A-clonecheck")
    seed_c = _make_seed(root, "clonecheck", login_password)
    serial_c = os.path.join(root, "serial-c.sock")
    monitor_c = os.path.join(root, "monitor-c.sock")
    proc = launch(root, system_c, persistence_disk, (seed_c,), serial_c, monitor_c,
                  extra_disks=(clone_disk,))
    con = console.SerialConsole(serial_c, connect_timeout=30)
    try:
        wait_for_login_prompt(con, timeout=240)
        login(con, SYNTH_LOGIN_USER, login_password)
        ev.record("bootC_login", True, "TestSystem-A booted with the original and its clone attached together")

        out = run_cmd(con, "sudo blkid /dev/vdb /dev/vdc", "CLONECHECK", timeout=15)
        ev.record("failure_cloned_signal_observable_when_simultaneous",
                   ("UUID=" in out) and (
                       out.count(out.split('UUID="')[1].split('"')[0]) >= 2 if 'UUID="' in out else False),
                   out)

        clean_shutdown(con, proc, timeout=120)
        ev.record("bootC_clean_shutdown", True, "guest exited")
    finally:
        con.close()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except Exception:
                proc.kill()
        for p in (serial_c, monitor_c):
            if os.path.exists(p):
                os.unlink(p)
    h.delete_validated_image(root, system_c)

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
        raise SystemExit(f"FAILED (sanitized): {_safe_message}") from None
    raise SystemExit(_rc)
