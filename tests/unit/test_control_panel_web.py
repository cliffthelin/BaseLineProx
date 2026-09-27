"""Unit tests for control_panel_web.py's routing/decision logic - the
real "Master Config" control-plane web app. Direct correction this
module exists to satisfy: "THIS IS A WEB APPLICATION... IT IS NOT A
FORM. I NEVER WILL PASTE RESULTS INTO IT OR GENERATE JSONS TO USE
SOMEWHERE ELSE." Every route here calls straight into the real,
already-tested backend modules (drive_installer, config_diff,
backup_restore, update_pipeline, config_crypto, physical_device_safety)
with a real Runner - no paste-in textarea, no "copy this command"
step anywhere. Exercises the handle_* functions directly with a
FakeRunner, not real sockets - the real HTTP wiring is a thin
pass-through, verified separately against a real running server (see
the decision record for this module).
"""
from fake_runner import FakeProc, FakeRunner

import control_panel_web as cpw


# -- detect -------------------------------------------------------------

def test_handle_detect_calls_the_real_backend_and_returns_its_result():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:1] == ["lvs"], FakeProc(0, "  pve  baseline_user_persistence_admin\n", "")),
    ])
    result = cpw.handle_detect(runner, vg_name="pve")
    assert result.outcome == "applied"
    assert result.status == 200
    assert result.body["found_volumes"] == ["baseline_user_persistence_admin"]


# -- active persona (work-queue item 25, decision record 78) --------------

def test_handle_active_persona_defaults_when_no_marker_exists():
    runner = FakeRunner()
    result = cpw.handle_active_persona(runner)
    assert result.outcome == "applied"
    assert result.body["persona"] == "admin"
    assert result.body["mountpoint"] == "/mnt/USER_PERSISTENCE_ADMIN"


def test_handle_active_persona_reflects_a_real_marker():
    import persist_bind_mounts as pbm
    runner = FakeRunner(files={pbm.ACTIVE_PERSONA_MARKER_PATH: "personal"})
    result = cpw.handle_active_persona(runner)
    assert result.body["persona"] == "personal"
    assert result.body["mountpoint"] == "/mnt/USER_PERSISTENCE_PERSONAL"


# -- differences ----------------------------------------------------------

def test_handle_differences_hands_off_when_no_config_file_exists():
    runner = FakeRunner()
    result = cpw.handle_differences(runner, config_path="/etc/baseline/install-config.json",
                                     network_interface="eno1")
    assert result.outcome == "handed_off"
    assert "install-config.json" in result.body["reason"]


def test_handle_differences_computes_the_real_diff_when_config_exists():
    import json
    config = {"proxmox": {"smartd_health_check": True}, "drivers": {}}
    runner = FakeRunner(files={"/etc/baseline/install-config.json": json.dumps(config)})
    result = cpw.handle_differences(runner, config_path="/etc/baseline/install-config.json",
                                     network_interface="eno1")
    assert result.outcome == "applied"
    sections = {s["subsystem"] for s in result.body["diff_sections"]}
    assert "smartd" in sections


# -- backup / list / restore -------------------------------------------------

def test_handle_backup_runs_the_real_tar_backup():
    runner = FakeRunner()
    result = cpw.handle_backup(runner, dest="/mnt/INSTALLER_CACHE/backups/x.tar.gz",
                                targets=["/mnt/USER_PERSISTENCE"], config_only=False)
    assert result.outcome == "applied"
    assert runner.calls[0][:2] == ["tar", "-czf"]


def test_handle_backup_refused_with_no_targets():
    runner = FakeRunner()
    result = cpw.handle_backup(runner, dest="/tmp/x.tar.gz", targets=[], config_only=False)
    assert result.outcome == "refused"
    assert runner.calls == []


def test_handle_backup_list_returns_the_real_tar_contents():
    runner = FakeRunner(command_responses=[
        (lambda a: a[:2] == ["tar", "-tzf"], FakeProc(0, "USER_PERSISTENCE/\nUSER_PERSISTENCE/doc.txt\n", "")),
    ])
    result = cpw.handle_backup_list(runner, archive="/tmp/x.tar.gz")
    assert result.outcome == "applied"
    assert result.body["contents"] == ["USER_PERSISTENCE/", "USER_PERSISTENCE/doc.txt"]


def test_handle_restore_runs_the_real_tar_extract():
    """An unconstrained restore (empty members) conservatively counts
    as touching USER_PERSISTENCE (decision record 74) - needs a fresh
    backup manifest to pass the hard gate, same as backup_restore's
    own tests."""
    import backup_restore
    runner = FakeRunner()
    backup_restore.record_backup_manifest(runner, target="/mnt/USER_PERSISTENCE", ts=1700000000.0)
    result = cpw.handle_restore(runner, archive="/tmp/x.tar.gz", dest_root="/mnt", members=[],
                                 now=1700000000.0 + 60)
    assert result.outcome == "applied"
    assert any(c[:2] == ["tar", "-xzf"] for c in runner.calls)


# -- update ----------------------------------------------------------------

def test_handle_update_hands_off_when_no_config_file_exists():
    runner = FakeRunner()
    result = cpw.handle_update(runner, config_path="/etc/baseline/install-config.json",
                                categories={"drivers": True}, network_interface="eno1")
    assert result.outcome == "handed_off"


def test_handle_update_applies_the_real_selective_update():
    import json
    config = {"proxmox": {}, "drivers": {"cpu_microcode": True, "cpu_microcode_package": "amd64-microcode"}}
    runner = FakeRunner(files={"/etc/baseline/install-config.json": json.dumps(config)})
    result = cpw.handle_update(runner, config_path="/etc/baseline/install-config.json",
                                categories={"drivers": True}, network_interface="eno1")
    assert result.outcome == "applied"
    assert "cpu_microcode" in result.body["applied"]


# -- validate-drive ----------------------------------------------------------

def test_handle_validate_drive_returns_the_real_validated_result():
    # physical_device_safety.Runner has its own shape - build one directly.
    import physical_device_safety as pds

    class PdsRunner(pds.Runner):
        def run(self, argv):
            if argv[0] == "udevadm":
                name_arg = next(a for a in argv if a.startswith("--name="))
                if name_arg == "--name=/dev/sdd":
                    return "ID_SERIAL_SHORT=REAL-SERIAL\n"
                return "ID_SERIAL_SHORT=BOOT-DRIVE-SERIAL\n"  # the boot device - a different, real serial
            if argv[0] == "findmnt":
                return "/dev/nvme0n1p2\n"
            if argv[0] == "lsblk":
                return "nvme0n1\n"
            raise AssertionError(argv)

        def lstat(self, path):
            import stat as statmod

            class S:
                st_mode = statmod.S_IFBLK
            return S()

        def realpath(self, path):
            return path

        def read_size_file(self, dev_name):
            return str(1_000_215_216)

    result = cpw.handle_validate_drive(PdsRunner(), path="/dev/sdd", min_size_bytes=500_000_000_000)
    assert result.outcome == "applied"
    assert result.body["serial"] == "REAL-SERIAL"


def test_handle_validate_drive_refuses_and_reports_the_real_reason():
    import physical_device_safety as pds

    class PdsRunner(pds.Runner):
        def run(self, argv):
            if argv[0] == "udevadm":
                return ""
            if argv[0] == "findmnt":
                return "/dev/nvme0n1p2\n"
            if argv[0] == "lsblk":
                return "nvme0n1\n"
            raise AssertionError(argv)

        def lstat(self, path):
            import stat as statmod

            class S:
                st_mode = statmod.S_IFREG  # not a block device
            return S()

        def realpath(self, path):
            return path

        def read_size_file(self, dev_name):
            return "0"

    result = cpw.handle_validate_drive(PdsRunner(), path="/dev/sdd", min_size_bytes=500_000_000_000)
    assert result.outcome == "refused"
    assert "block device" in result.body["error"]
