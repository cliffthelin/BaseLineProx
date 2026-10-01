"""Unit tests for self_installer.py - the composed "make a real drive
a self-installer" pipeline. Every stage is FakeRunner-scripted, reusing
each already-existing module's own test fakes (matching this project's
cross-test-file reuse precedent, e.g. test_firstboot_statemachine.py
importing from test_phase0_additive_repair.py) - no real network,
subprocess, QEMU, or block device anywhere in this file."""
import tomllib
from pathlib import Path

import pytest

import self_installer as si
import drive_setup_answer as dsan
from test_physical_device_safety import FakeRunner as FakePdsRunner
from test_drive_setup_acquire import FakeAcquireRunner
from test_drive_setup_answer import FakeAnswerRunner
from test_iso_builder import FakeIsoBuilderRunner
from test_drive_setup_install import FakeInstallRunner, FakeInstallProcess


@pytest.fixture(autouse=True)
def _reset_active_answer_server():
    """`si._active_answer_server` (decision record 115) is real,
    intentional module-level state (one process, one port) - but that
    means it survives across tests in the same pytest process unless
    reset, which would make later tests' behavior depend on test
    order. Reset it before and after every test in this file."""
    si._active_answer_server = None
    yield
    si._active_answer_server = None


# -- Real bug found by the QEMU disposable-install smoke test (decision
# record 93): Proxmox's own answer-file schema requires
# lvm.maxroot/maxvz/swapsize as a plain number (f64) - a quoted "40G"
# string is a hard TOML-schema parse error
# ("invalid type: string \"40G\", expected f64") that would have
# failed every real self-installer run. No prior unit test ever
# actually parsed the rendered answer.toml with a real TOML parser -
# every one of them used a FakeAnswerRunner that never validated
# content, only intercepted the call. This test uses tomllib (stdlib)
# to genuinely parse the rendered template and assert real types,
# not just string-match for absent quotes. ---------------------------

def test_answer_template_renders_lvm_sizes_as_real_numbers_not_quoted_strings():
    for preset in si.LVM_SIZE_PRESETS.values():
        rendered = si.ANSWER_TEMPLATE.format(
            fqdn="baseline.local", password_hash="$6$x$y", disk_serial="ABC123", **preset,
        )
        parsed = tomllib.loads(rendered)
        disk_setup = parsed["disk-setup"]
        assert isinstance(disk_setup["lvm"]["maxroot"], (int, float))
        assert isinstance(disk_setup["lvm"]["maxvz"], (int, float))
        assert isinstance(disk_setup["lvm"]["swapsize"], (int, float))
        assert disk_setup["lvm"]["maxroot"] == preset["lvm_maxroot"]


def test_lvm_size_presets_are_plain_numbers_not_g_suffixed_strings():
    for preset in si.LVM_SIZE_PRESETS.values():
        for key in ("lvm_maxroot", "lvm_maxvz", "lvm_swapsize"):
            assert isinstance(preset[key], (int, float)), f"{key} must be a real number, not {preset[key]!r}"


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


def test_on_progress_receives_real_stage_descriptions(tmp_path):
    """Direct instruction, 2026-09-29: "add a console log of what is
    running and doing" - the pipeline reports each real stage as it
    happens, not a fake/simulated percentage."""
    lines = []
    si.build_and_write_self_installer(**_ready_kwargs(tmp_path), on_progress=lines.append)
    assert any("Validating" in line and "/dev/sdd" in line for line in lines)
    assert any("Target confirmed" in line for line in lines)
    assert any("cached Proxmox source ISO" in line for line in lines)


def test_on_progress_surfaces_the_real_one_time_password_never_just_discards_it(tmp_path):
    """Real bug found live, 2026-09-29: the generated one-time Proxmox
    root password used to be `del`d immediately after being hashed for
    the answer file - genuinely never shown to the operator anywhere.
    Direct instruction: the code must actually tell the operator what
    it is. Proves the plaintext password now reaches on_progress, not
    just its hash."""
    lines = []
    kwargs = _ready_kwargs(tmp_path)
    kwargs["acquire_runner"].files[str(kwargs["assistant_binary"])] = b"cached-binary"
    si.build_and_write_self_installer(**kwargs, on_progress=lines.append)
    password_lines = [line for line in lines if "one-time Proxmox root password" in line]
    assert password_lines, f"no password line found in: {lines}"
    # the surfaced text must contain an actual password value, not just the label
    assert len(password_lines[0].split(":")[-1].strip()) > 8


def test_answer_toml_uses_the_real_detected_serial_not_expected_serial(tmp_path, monkeypatch):
    """Real bug found live, 2026-09-29: the answer file's own
    `filter.ID_SERIAL_SHORT` used to be populated from `expected_serial`
    (the optional, usually-`None` human-override param) instead of the
    real, already-detected device serial - baking the literal string
    "None" into the real answer file, which Proxmox's own installer
    correctly refused: "Installation failed: filter did not match any
    device." Every existing test happened to pass `expected_serial`
    equal to the real detected serial, completely masking this - this
    test deliberately omits it (`expected_serial=None`, the real
    production default) to prove the fix."""
    import drive_setup_answer as dsan_module

    captured = {}
    real_prepare = dsan_module.prepare_iso_defensively

    def capturing_prepare(*args, **kwargs):
        captured.update(kwargs)
        return real_prepare(*args, **kwargs)

    monkeypatch.setattr(dsan_module, "prepare_iso_defensively", capturing_prepare)
    kwargs = _ready_kwargs(tmp_path, expected_serial=None)
    kwargs["acquire_runner"].files[str(kwargs["assistant_binary"])] = b"cached-binary"
    si.build_and_write_self_installer(**kwargs)  # refuses at prepare-iso itself (unscripted success) - fine, it's already been called by then
    answer_toml = captured["forbidden_iso_strings"][1].decode()
    assert REAL_SERIAL in answer_toml
    assert 'filter.ID_SERIAL_SHORT = "None"' not in answer_toml


def test_admin_password_reuses_the_submitted_password_instead_of_generating_one(tmp_path):
    """Direct instruction, 2026-09-29: "It has to accept my root
    password in Linux now" - when `admin_password` is given, it (not a
    freshly generated one-time password) becomes the new Proxmox
    install's real root password, and the plaintext is never echoed
    back (the operator already knows it - they just typed it)."""
    lines = []
    kwargs = _ready_kwargs(tmp_path)
    kwargs["acquire_runner"].files[str(kwargs["assistant_binary"])] = b"cached-binary"
    si.build_and_write_self_installer(**kwargs, on_progress=lines.append, admin_password="my-real-shared-password")
    assert any("Using the password you submitted" in line for line in lines)
    assert not any("Generated one-time" in line for line in lines)
    assert not any("my-real-shared-password" in line for line in lines)  # never echoed back


def test_displayed_one_time_password_is_clean_text_not_a_bytes_repr(tmp_path):
    """Real bug found live, 2026-09-29: `generate_one_time_password()`
    returns real `bytes` - embedding it directly in an f-string
    rendered Python's own `b'...'` repr (quotes and the `b` prefix
    included) as if that were part of the real password. If someone
    typed the displayed text verbatim (including `b'` and the trailing
    `'`), login would fail."""
    lines = []
    kwargs = _ready_kwargs(tmp_path)
    kwargs["acquire_runner"].files[str(kwargs["assistant_binary"])] = b"cached-binary"
    si.build_and_write_self_installer(**kwargs, on_progress=lines.append)
    password_line = next(line for line in lines if "one-time Proxmox root password" in line)
    shown = password_line.split(":")[1].split("<--")[0].strip()
    assert not shown.startswith("b'")
    assert not shown.endswith("'")


def test_build_and_write_self_installer_forwards_guestfwd_to_qemu_invocation(tmp_path, monkeypatch):
    """Real bug found live, 2026-09-29 (a regression from decision
    record 03's own already-proven fix): the real install's own
    answer-file POST got a real `Connection refused` because plain
    `-nic user,restrict=on` cannot reach any host-bound TCP service -
    confirmed directly, twice. `server_host`/`server_port` (the
    guestfwd-forwarded address the answer file itself already embeds)
    must reach `build_sparse_install_invocation` as `guestfwd_host`/
    `guestfwd_port`, not be silently dropped."""
    import drive_setup_install as dsi
    import iso_builder as ib

    captured = {}

    def fake_invocation(**kwargs):
        captured.update(kwargs)
        raise _StopAfterInvocation()

    class _StopAfterInvocation(Exception):
        pass

    monkeypatch.setattr(dsi, "build_sparse_install_invocation", fake_invocation)
    monkeypatch.setattr(dsan, "prepare_iso_defensively",
                         lambda *a, **k: dsan.PrepareIsoOutcome(ok=True, output_path=Path("/ws/answer-embedded.iso")))
    monkeypatch.setattr(ib, "build_current_iso",
                         lambda *a, **k: ib.IsoBuildResult(ok=True, output_path=Path("/ws/final.iso")))

    kwargs = _ready_kwargs(tmp_path)
    kwargs["acquire_runner"].files[str(kwargs["assistant_binary"])] = b"cached-binary"

    try:
        si.build_and_write_self_installer(**kwargs)
        assert False, "expected _StopAfterInvocation to be raised"
    except _StopAfterInvocation:
        pass

    assert captured.get("guestfwd_host") == kwargs["server_host"]
    assert captured.get("guestfwd_port") == 8443


def test_build_and_write_self_installer_forwards_disk_serial_to_qemu_invocation(tmp_path, monkeypatch):
    """Real bug found live, 2026-09-29 (decision record 114): the
    answer file's own `filter.ID_SERIAL_SHORT` already carries the
    real detected serial (decision record 112) - but the QEMU
    invocation itself never exposed that same serial to the VM, so
    Proxmox's installer could never actually match its own filter.
    Confirmed live with decision record 112's fix already applied and
    correct: "Installation failed: filter did not match any device"
    still happened. `disk_serial` (the same real, already-detected
    value the answer file uses) must reach
    `build_sparse_install_invocation` as `target_serial`."""
    import drive_setup_install as dsi
    import iso_builder as ib

    captured = {}

    class _StopAfterInvocation(Exception):
        pass

    def fake_invocation(**kwargs):
        captured.update(kwargs)
        raise _StopAfterInvocation()

    monkeypatch.setattr(dsi, "build_sparse_install_invocation", fake_invocation)
    monkeypatch.setattr(dsan, "prepare_iso_defensively",
                         lambda *a, **k: dsan.PrepareIsoOutcome(ok=True, output_path=Path("/ws/answer-embedded.iso")))
    monkeypatch.setattr(ib, "build_current_iso",
                         lambda *a, **k: ib.IsoBuildResult(ok=True, output_path=Path("/ws/final.iso")))

    kwargs = _ready_kwargs(tmp_path)
    kwargs["acquire_runner"].files[str(kwargs["assistant_binary"])] = b"cached-binary"

    try:
        si.build_and_write_self_installer(**kwargs)
        assert False, "expected _StopAfterInvocation to be raised"
    except _StopAfterInvocation:
        pass

    assert captured.get("target_serial") == REAL_SERIAL


def test_kills_stale_qemu_process_before_launching_a_new_one(tmp_path, monkeypatch):
    """Real bug found live, 2026-09-29 (decision record 113): nothing
    ever killed a *previous* run's own QEMU process before launching a
    new one. Confirmed via a real install whose live QEMU process
    predated its own workspace's freshly rebuilt ISO/answer-server
    files by five minutes - a prior attempt's process, silently
    stalled, still holding the real device and monitor socket while a
    new job's own progress log claimed a fresh install was running. A
    monitor-socket file already present at this workspace path is
    real, direct evidence that a prior process may still be alive."""
    import drive_setup_install as dsi
    import iso_builder as ib

    class _StopAfterPopen(Exception):
        pass

    monkeypatch.setattr(dsan, "prepare_iso_defensively",
                         lambda *a, **k: dsan.PrepareIsoOutcome(ok=True, output_path=Path("/ws/answer-embedded.iso")))
    monkeypatch.setattr(ib, "build_current_iso",
                         lambda *a, **k: ib.IsoBuildResult(ok=True, output_path=Path("/ws/final.iso")))
    monkeypatch.setattr(dsi, "build_sparse_install_invocation",
                         lambda **k: dsi.QemuInvocation(argv=["qemu-system-x86_64"]))
    monkeypatch.setattr(dsan, "SessionState", lambda *a, **k: (_ for _ in ()).throw(_StopAfterPopen()))

    kwargs = _ready_kwargs(tmp_path)
    kwargs["acquire_runner"].files[str(kwargs["assistant_binary"])] = b"cached-binary"
    monitor_socket = kwargs["workspace"] / "monitor.sock"
    kwargs["install_runner"].existing_paths.add(str(monitor_socket))
    kwargs["install_runner"].scripted_popen_process = FakeInstallProcess()

    lines = []
    try:
        si.build_and_write_self_installer(**kwargs, on_progress=lines.append)
        assert False, "expected _StopAfterPopen to be raised"
    except _StopAfterPopen:
        pass

    assert str(monitor_socket) in kwargs["install_runner"].killed_paths
    assert any("previous run" in line.lower() for line in lines)


def test_does_not_attempt_to_kill_anything_when_no_stale_process_exists(tmp_path, monkeypatch):
    """The kill call is real and only fires when the monitor socket
    file genuinely already exists - a fresh workspace's first-ever run
    must never call it."""
    import drive_setup_install as dsi
    import iso_builder as ib

    class _StopAfterPopen(Exception):
        pass

    monkeypatch.setattr(dsan, "prepare_iso_defensively",
                         lambda *a, **k: dsan.PrepareIsoOutcome(ok=True, output_path=Path("/ws/answer-embedded.iso")))
    monkeypatch.setattr(ib, "build_current_iso",
                         lambda *a, **k: ib.IsoBuildResult(ok=True, output_path=Path("/ws/final.iso")))
    monkeypatch.setattr(dsi, "build_sparse_install_invocation",
                         lambda **k: dsi.QemuInvocation(argv=["qemu-system-x86_64"]))
    monkeypatch.setattr(dsan, "SessionState", lambda *a, **k: (_ for _ in ()).throw(_StopAfterPopen()))

    kwargs = _ready_kwargs(tmp_path)
    kwargs["acquire_runner"].files[str(kwargs["assistant_binary"])] = b"cached-binary"
    kwargs["install_runner"].scripted_popen_process = FakeInstallProcess()

    try:
        si.build_and_write_self_installer(**kwargs)
        assert False, "expected _StopAfterPopen to be raised"
    except _StopAfterPopen:
        pass

    assert kwargs["install_runner"].killed_paths == []


class _FakeAnswerServer:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def test_stops_a_previous_answer_server_before_starting_a_new_one(tmp_path, monkeypatch):
    """Real bug found live, 2026-09-29 (decision record 115): a
    previous run's own `EphemeralAnswerServer` was never stopped
    before a new one tried to bind the same port. Confirmed live via a
    real retry that got a real `OSError: [Errno 98] Address already in
    use` - and, on an earlier retry where the bind happened to still
    succeed, a real answer-file-fetch timeout where the VM's
    request silently reached a *stale* server from an even older run
    whose session token didn't match. The fix tracks the single
    currently-active server at module level (mirroring decision record
    113's same fix for the QEMU process) and stops it first."""
    import drive_setup_install as dsi
    import iso_builder as ib

    monkeypatch.setattr(dsan, "prepare_iso_defensively",
                         lambda *a, **k: dsan.PrepareIsoOutcome(ok=True, output_path=Path("/ws/answer-embedded.iso")))
    monkeypatch.setattr(ib, "build_current_iso",
                         lambda *a, **k: ib.IsoBuildResult(ok=True, output_path=Path("/ws/final.iso")))
    monkeypatch.setattr(dsi, "build_sparse_install_invocation",
                         lambda **k: dsi.QemuInvocation(argv=["qemu-system-x86_64"]))
    monkeypatch.setattr(dsan, "EphemeralAnswerServer", _FakeAnswerServer)

    kwargs = _ready_kwargs(tmp_path)
    kwargs["acquire_runner"].files[str(kwargs["assistant_binary"])] = b"cached-binary"
    kwargs["install_runner"].scripted_popen_process = FakeInstallProcess()

    # First run: nothing previously active - must not call stop() on
    # anything, and must record itself as the new active server.
    si.build_and_write_self_installer(**kwargs)
    first_server = si._active_answer_server
    assert first_server is not None
    assert first_server.started is True
    assert first_server.stopped is False

    # Second run: the first server is still "listening" (never
    # stopped) - it must be stopped before the second one starts.
    lines = []
    kwargs["install_runner"].scripted_popen_process = FakeInstallProcess()
    si.build_and_write_self_installer(**kwargs, on_progress=lines.append)

    assert first_server.stopped is True
    second_server = si._active_answer_server
    assert second_server is not None
    assert second_server is not first_server
    assert second_server.started is True
    assert any("previous run's answer server" in line.lower() for line in lines)


def test_does_not_attempt_to_stop_anything_on_the_very_first_run(tmp_path, monkeypatch):
    """No previous server exists on a fresh workspace's first-ever
    run - the progress log must never mention stopping one."""
    import drive_setup_install as dsi
    import iso_builder as ib

    monkeypatch.setattr(dsan, "prepare_iso_defensively",
                         lambda *a, **k: dsan.PrepareIsoOutcome(ok=True, output_path=Path("/ws/answer-embedded.iso")))
    monkeypatch.setattr(ib, "build_current_iso",
                         lambda *a, **k: ib.IsoBuildResult(ok=True, output_path=Path("/ws/final.iso")))
    monkeypatch.setattr(dsi, "build_sparse_install_invocation",
                         lambda **k: dsi.QemuInvocation(argv=["qemu-system-x86_64"]))
    monkeypatch.setattr(dsan, "EphemeralAnswerServer", _FakeAnswerServer)

    kwargs = _ready_kwargs(tmp_path)
    kwargs["acquire_runner"].files[str(kwargs["assistant_binary"])] = b"cached-binary"
    kwargs["install_runner"].scripted_popen_process = FakeInstallProcess()

    lines = []
    si.build_and_write_self_installer(**kwargs, on_progress=lines.append)
    assert not any("previous run's answer server" in line.lower() for line in lines)


def test_on_progress_defaults_to_a_no_op_when_omitted(tmp_path):
    # Must not raise just because no callback was given.
    si.build_and_write_self_installer(**_ready_kwargs(tmp_path))


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


# -- Decision record 86: "everything must be selectable without a
# keyboard" - device_path is the only thing a human ever supplies;
# everything else below must be derivable/generatable/locatable on its
# own, and refuse clearly (never crash) when it genuinely can't be. --

def test_refuses_when_the_selected_device_reports_no_hardware_serial(tmp_path):
    no_serial_pds = FakePdsRunner(udevadm_by_path={}, findmnt_root="/dev/nvme0n1p2",
                                   pkname_of_root="nvme0n1", sizes={"sdd": 1_000_000_000_000 // 512})
    kwargs = _ready_kwargs(tmp_path, pds_runner=no_serial_pds, expected_serial=None)
    result = si.build_and_write_self_installer(**kwargs)
    assert result.outcome == "refused"
    assert "no hardware serial" in result.detail


def test_generates_its_own_cert_and_key_when_none_supplied(tmp_path):
    kwargs = _ready_kwargs(tmp_path, cert_path=None, key_path=None)
    kwargs["answer_runner"].script(lambda a: a[:2] == ["openssl", "req"], dsan.AnswerProc(0, "", ""))
    result = si.build_and_write_self_installer(**kwargs)
    # Reaches (and fails) the next real stage - proves cert generation
    # itself didn't refuse or raise, and never asked a human for a path.
    assert result.outcome == "refused"
    assert "no hardware serial" not in result.detail
    assert "generating ephemeral TLS cert" not in result.detail


def test_refuses_clearly_when_no_proxmox_source_iso_can_be_located(tmp_path):
    kwargs = _ready_kwargs(tmp_path, proxmox_source_iso=None)
    result = si.build_and_write_self_installer(**kwargs)
    assert result.outcome == "refused"
    assert "no Proxmox source ISO found" in result.detail


def test_server_host_defaults_to_the_guestfwd_forwarded_address():
    """Real bug found live, 2026-09-29 (a regression from decision
    record 03's own already-proven fix): `10.0.2.2` is SLIRP's own
    gateway - a real host-bound TCP service is not reachable there at
    all under `restrict=on` (confirmed directly, twice, with a real
    `Connection refused`). `10.0.2.100` is the distinct, guestfwd-
    forwarded address decision record 03 already proved working."""
    assert si.DEFAULT_SERVER_HOST == "10.0.2.100"
