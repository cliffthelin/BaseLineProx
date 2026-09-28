"""Unit tests for self_installer.py - the composed "make a real drive
a self-installer" pipeline. Every stage is FakeRunner-scripted, reusing
each already-existing module's own test fakes (matching this project's
cross-test-file reuse precedent, e.g. test_firstboot_statemachine.py
importing from test_phase0_additive_repair.py) - no real network,
subprocess, QEMU, or block device anywhere in this file."""
import self_installer as si
import drive_setup_answer as dsan
from test_physical_device_safety import FakeRunner as FakePdsRunner
from test_drive_setup_acquire import FakeAcquireRunner
from test_drive_setup_answer import FakeAnswerRunner
from test_iso_builder import FakeIsoBuilderRunner
from test_drive_setup_install import FakeInstallRunner


REAL_SERIAL = "FD01N6557110C271B"


def _pds_runner_ok():
    return FakePdsRunner(
        udevadm_by_path={"/dev/sdd": REAL_SERIAL},
        findmnt_root="/dev/nvme0n1p2", pkname_of_root="nvme0n1",
        sizes={"sdd": 1_000_000_000_000 // 512},  # sectors -> ~500GB
    )


def _ready_kwargs(tmp_path, **overrides):
    answer_runner = FakeAnswerRunner()
    cert = tmp_path / "cert.pem"
    cert.write_text("stub")
    answer_runner.files[str(cert)] = b"stub"
    answer_runner.script(lambda a: a[:2] == ["openssl", "x509"], dsan.AnswerProc(0, "sha256 Fingerprint=AA:BB:CC\n", ""))

    kwargs = dict(
        device_path="/dev/sdd", expected_serial=REAL_SERIAL, device_min_size_bytes=1,
        pds_runner=_pds_runner_ok(),
        acquire_runner=FakeAcquireRunner(), answer_runner=answer_runner,
        iso_builder_runner=FakeIsoBuilderRunner(), install_runner=FakeInstallRunner(),
        workspace=tmp_path / "ws", repo_root=tmp_path / "repo",
        proxmox_source_iso=tmp_path / "proxmox.iso", assistant_binary=tmp_path / "assistant",
        server_host="10.0.0.231", cert_path=cert, key_path=tmp_path / "key.pem",
    )
    kwargs.update(overrides)
    return kwargs


def test_refuses_before_anything_else_on_device_safety_failure(tmp_path):
    bad_pds = FakePdsRunner(udevadm_by_path={"/dev/sdd": "WRONG-SERIAL"},
                             findmnt_root="/dev/nvme0n1p2", pkname_of_root="nvme0n1",
                             sizes={"sdd": 1_000_000_000_000 // 512})
    result = si.build_and_write_self_installer(**_ready_kwargs(tmp_path, pds_runner=bad_pds))
    assert result.outcome == "refused"
    assert "device safety check failed" in result.detail


def test_skips_acquire_entirely_when_assistant_already_cached(tmp_path):
    kwargs = _ready_kwargs(tmp_path)
    kwargs["acquire_runner"].files[str(kwargs["assistant_binary"])] = b"cached-binary"
    # No prepare-iso success scripted - this will refuse at the next
    # stage, which is fine; the only thing under test here is that
    # acquire's own fetch chain was never touched at all.
    si.build_and_write_self_installer(**kwargs)
    assert kwargs["acquire_runner"].calls == []


def test_refuses_when_acquire_fails(tmp_path):
    kwargs = _ready_kwargs(tmp_path)
    # FakeAcquireRunner with no scripted responses fails the very first fetch step.
    result = si.build_and_write_self_installer(**kwargs)
    assert result.outcome == "refused"
    assert "acquiring proxmox-auto-install-assistant failed" in result.detail


def test_refuses_when_prepare_iso_fails(tmp_path):
    kwargs = _ready_kwargs(tmp_path)
    kwargs["acquire_runner"].files[str(kwargs["assistant_binary"])] = b"cached"
    kwargs["answer_runner"].script(lambda a: a[1:2] == ["prepare-iso"], dsan.AnswerProc(0, "Error: boom", ""))
    result = si.build_and_write_self_installer(**kwargs)
    assert result.outcome == "refused"
    assert "prepare-iso failed" in result.detail


def test_never_launches_qemu_when_any_earlier_stage_fails(tmp_path):
    kwargs = _ready_kwargs(tmp_path)
    result = si.build_and_write_self_installer(**kwargs)
    assert result.outcome == "refused"
    assert kwargs["install_runner"].calls == []
