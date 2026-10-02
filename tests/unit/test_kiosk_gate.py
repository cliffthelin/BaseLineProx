"""Unit tests for kiosk_gate.py (Track A3) - the ExecStartPre check that
refuses to launch the kiosk GUI until baseline-firstboot.service has
genuinely committed. Reuses firstboot_statemachine.already_completed()'s
existence-based, fail-closed discipline unchanged - never re-implements
its own notion of "done"."""
import kiosk_gate


def test_refuses_when_not_completed(tmp_path):
    rc = kiosk_gate.check(state_dir=tmp_path)
    assert rc == 1


def test_allows_when_completed(tmp_path):
    marker = tmp_path / "complete"
    marker.write_text("2026-01-01T00:00:00\n")
    rc = kiosk_gate.check(state_dir=tmp_path)
    assert rc == 0


def test_kiosk_unit_can_take_its_terminal_and_has_a_private_runtime_directory():
    from pathlib import Path
    unit = (Path(__file__).resolve().parents[2] / "boot/baseline-kiosk.service").read_text()
    assert "StandardInput=tty-force" in unit
    assert "RuntimeDirectory=cage-kiosk" in unit and "RuntimeDirectoryMode=0700" in unit
    assert "Environment=LIBSEAT_BACKEND=builtin" in unit
    assert "ExecStartPre=/opt/baseline/bin/baseline-kiosk-gate" in unit


def test_provision_installs_the_ubuntu_seed_builder_and_download_dependencies():
    from pathlib import Path
    import shlex
    script = (Path(__file__).resolve().parents[2] / "boot/provision.sh").read_text()
    installed = set()
    for line in script.splitlines():
        if not line.strip().startswith("apt-get install "):
            continue
        args = shlex.split(line, comments=True)
        if args[:2] == ["apt-get", "install"]:
            installed.update(arg for arg in args[2:] if not arg.startswith("-"))
    assert {"cage", "chromium", "xorriso", "curl"} <= installed
