"""Independent fake-only probes against b1a0fea, the parent of df4a84a."""
import physical_device_safety as pds
from test_drive_admin import FakePdsRunner
from test_lay_out_action import BLANK, Runner
from hitl_helpers import perform_confirmed


def test_review_parent_layout_refuses_serial_change_after_confirmation(monkeypatch):
    import drive_guard as dg
    monkeypatch.setattr(dg, "_default_run", lambda argv: (0, BLANK))
    pds_runner = FakePdsRunner(size_bytes=512_110_190_592, drive_table=BLANK)

    class SwappingRunner(Runner):
        def run(self, argv, timeout=10):
            if argv[0] == "lsblk":
                pds_runner.serial = "NOTENROLLEDREVIEW1"
            return super().run(argv, timeout)

    runner = SwappingRunner()
    result = perform_confirmed(runner, "lay_out_baseline_drive", {"device_path": "/dev/sdb"},
                               pds_runner=pds_runner)
    assert not [c for c in runner.calls if c[0] in ("wipefs", "sgdisk", "mkfs.ext4")]
    assert not result.ok


def test_review_parent_device_gate_refuses_unknown_boot_identity():
    runner = FakePdsRunner(serial="UNKNOWNBOOTREVIEW1", findmnt_root="")
    rejected = False
    try:
        pds.validate_target_device("/dev/sdc", expected_serial="UNKNOWNBOOTREVIEW1",
                                  min_size_bytes=50_000_000_000, runner=runner)
    except pds.PhysicalDeviceSafetyError:
        rejected = True
    assert rejected
