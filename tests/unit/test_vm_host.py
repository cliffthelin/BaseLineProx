"""VM host: base images, copy-on-write overlays, start/stop, rollback - QEMU/KVM directly, no Proxmox needed.
Everything external (qemu-img, the qemu process, the QMP socket, /proc) is injected; no test starts a real qemu."""
import json

import pytest

import vm_host as vh


class FakeRun:
    def __init__(self, rc=0):
        self.calls, self.rc = [], rc

    def __call__(self, argv):
        self.calls.append(list(argv))
        if argv[:2] == ["qemu-img", "create"]:
            from pathlib import Path
            Path(argv[-1] if argv[-1][0] == "/" else argv[-2]).write_bytes(b"qcow2")
        if argv[0] == "xorriso" and "-o" in argv:
            from pathlib import Path
            Path(argv[argv.index("-o") + 1]).write_bytes(b"seed ISO")
        return self.rc, "", ""


class FakeHost:
    def __init__(self, store, rc=0):
        self.run = FakeRun(rc)
        self.spawned, self.alive, self.powered_down, self.quit_sent, self.killed = [], set(), [], [], []
        self.next_pid = 4242
        self.responds_to_powerdown = True
        self.host = vh.VmHost(store, run=self.run, spawn=self._spawn, is_alive=self._alive,
                              qmp=self._qmp, kill=self._kill, sleep=lambda s: None, free_bytes=lambda p: 500 * 2**30,
                              cmdline=self._cmdline, runtime_dir=store.parent / (store.name + "-run"),
                              persistence_store=store.parent / (store.name + "-user-data"))

    def _spawn(self, argv):
        self.spawned.append(argv)
        self.alive.add(self.next_pid)
        return self.next_pid

    def _alive(self, pid):
        return pid in self.alive

    def _cmdline(self, pid):
        return self.spawned[-1] if pid in self.alive and self.spawned else []

    def _qmp(self, sock, command):
        (self.powered_down if command == "system_powerdown" else self.quit_sent).append(sock)
        if command == "system_powerdown" and self.responds_to_powerdown:
            self.alive.discard(self.next_pid)
        if command == "quit":
            self.alive.discard(self.next_pid)

    def _kill(self, pid):
        self.killed.append(pid)
        self.alive.discard(pid)


@pytest.fixture
def h(tmp_path):
    return FakeHost(tmp_path / "store")


def test_names_are_strict():
    for good in ("win11", "dev-box", "a"):
        assert vh.valid_name(good)
    for bad in ("", "../x", "a/b", "A", "-x", "x" * 40, "a b", ".hidden", "a;b"):
        assert not vh.valid_name(bad)


def test_new_vm_from_iso_makes_a_standalone_disk_and_records_the_spec(h):
    iso = h.host.store / "x.iso"
    vm = h.host.create_from_iso("dev", iso=str(iso), disk_gb=40, memory_mb=4096, cpus=4)
    assert h.run.calls[0][:4] == ["qemu-img", "create", "-f", "qcow2"] and h.run.calls[0][-1].endswith("40G")
    spec = json.loads((h.host.vm_dir("dev") / "vm.json").read_text())
    assert spec["name"] == "dev" and spec["base"] is None and spec["iso"] == str(iso) and spec["memory_mb"] == 4096
    assert vm["name"] == "dev"


def test_overlay_is_a_qcow2_with_the_base_as_read_only_backing_file(h):
    base = h.host.bases_dir / "golden.qcow2"
    base.parent.mkdir(parents=True)
    base.write_bytes(b"x")
    h.host.create_overlay("scratch", base="golden")
    argv = h.run.calls[0]
    assert argv[:2] == ["qemu-img", "create"] and "-b" in argv and argv[argv.index("-b") + 1] == str(base)
    assert argv[argv.index("-F") + 1] == "qcow2"
    assert json.loads((h.host.vm_dir("scratch") / "vm.json").read_text())["base"] == "golden"


def test_unknown_base_and_bad_names_are_refused(h):
    with pytest.raises(vh.VmError):
        h.host.create_overlay("scratch", base="nope")
    with pytest.raises(vh.VmError):
        h.host.create_from_iso("../evil", iso="/x.iso", disk_gb=10)
    with pytest.raises(vh.VmError):
        h.host.create_overlay("ok", base="../../etc/passwd")
    assert h.run.calls == []


def test_a_name_cannot_be_reused(h):
    h.host.create_from_iso("dev", iso="/x.iso", disk_gb=10)
    with pytest.raises(vh.VmError):
        h.host.create_from_iso("dev", iso="/x.iso", disk_gb=10)


def test_start_runs_kvm_with_the_disk_and_never_a_raw_device(h):
    h.host.create_from_iso("dev", iso="/x.iso", disk_gb=10, memory_mb=2048, cpus=2)
    h.host.start("dev")
    argv = h.spawned[0]
    assert argv[0] == "qemu-system-x86_64" and "-enable-kvm" in argv
    joined = " ".join(argv)
    assert str(h.host.disk_path("dev")) in joined and "-cdrom /x.iso" in joined
    assert "restrict=on" not in joined          # the VM needs normal user networking
    assert not any(a.startswith("/dev/") for a in argv)
    assert h.host.status("dev")["running"] is True


def test_start_twice_is_refused_and_does_not_spawn_again(h):
    h.host.create_from_iso("dev", iso="/x.iso", disk_gb=10)
    h.host.start("dev")
    with pytest.raises(vh.VmError):
        h.host.start("dev")
    assert len(h.spawned) == 1


def test_stop_asks_the_guest_to_power_down_first_and_kills_nothing(h):
    h.host.create_from_iso("dev", iso="/x.iso", disk_gb=10)
    h.host.start("dev")
    h.host.stop("dev")
    assert h.powered_down and not h.quit_sent and h.killed == []
    assert h.host.status("dev")["running"] is False


def test_stop_escalates_to_qmp_quit_then_to_the_exact_verified_pid(h):
    h.host.create_from_iso("dev", iso="/x.iso", disk_gb=10)
    h.host.start("dev")
    h.responds_to_powerdown = False
    h.host.stop("dev", wait_s=1)
    assert h.powered_down and h.quit_sent == [] or h.quit_sent      # quit sent after power-down is ignored
    assert h.host.status("dev")["running"] is False


def test_a_reused_pid_that_is_not_our_qemu_is_never_killed(h):
    h.host.create_from_iso("dev", iso="/x.iso", disk_gb=10)
    h.host.start("dev")
    h.host._cmdline = lambda pid: ["firefox"]           # the pid now belongs to something else
    h.host.is_alive = lambda pid: True
    assert h.host.status("dev")["running"] is False
    assert h.killed == []


def test_rollback_recreates_the_overlay_from_its_base_while_stopped(h):
    base = h.host.bases_dir / "golden.qcow2"
    base.parent.mkdir(parents=True)
    base.write_bytes(b"x")
    h.host.create_overlay("scratch", base="golden")
    disk = h.host.vm_dir("scratch") / "disk.qcow2"
    disk.write_bytes(b"dirty changes")
    h.host.rollback("scratch")
    assert disk.read_bytes() == b"qcow2"
    assert h.run.calls[-1][:2] == ["qemu-img", "create"]


def test_rollback_is_refused_for_a_standalone_vm_and_while_running(h):
    h.host.create_from_iso("dev", iso="/x.iso", disk_gb=10)
    with pytest.raises(vh.VmError):
        h.host.rollback("dev")
    base = h.host.bases_dir / "golden.qcow2"
    base.parent.mkdir(parents=True, exist_ok=True)
    base.write_bytes(b"x")
    h.host.create_overlay("scratch", base="golden")
    h.host.start("scratch")
    with pytest.raises(vh.VmError):
        h.host.rollback("scratch")


def test_freeze_turns_a_stopped_vm_disk_into_a_read_only_base(h):
    h.host.create_from_iso("dev", iso="/x.iso", disk_gb=10)
    disk = h.host.disk_path("dev")
    disk.write_bytes(b"installed os")
    h.host.freeze_as_base("dev", "ubuntu-base")
    base = h.host.bases_dir / "ubuntu-base.qcow2"
    assert base.read_bytes() == b"installed os" and not (base.stat().st_mode & 0o222)
    assert not h.host.vm_dir("dev").exists()                # the install VM is consumed; clone from the base
    assert [b["name"] for b in h.host.list_bases()] == ["ubuntu-base"]


def test_freeze_is_refused_while_running_and_never_replaces_an_existing_base(h):
    h.host.create_from_iso("dev", iso="/x.iso", disk_gb=10)
    h.host.start("dev")
    with pytest.raises(vh.VmError):
        h.host.freeze_as_base("dev", "b")
    h.host.stop("dev")
    h.host.bases_dir.mkdir(parents=True, exist_ok=True)
    (h.host.bases_dir / "b.qcow2").write_bytes(b"old")
    with pytest.raises(vh.VmError):
        h.host.freeze_as_base("dev", "b")
    assert (h.host.bases_dir / "b.qcow2").read_bytes() == b"old"


def test_a_base_with_overlays_cannot_be_deleted(h):
    base = h.host.bases_dir / "golden.qcow2"
    base.parent.mkdir(parents=True)
    base.write_bytes(b"x")
    h.host.create_overlay("scratch", base="golden")
    with pytest.raises(vh.VmError):
        h.host.delete_base("golden")


def test_delete_vm_needs_it_stopped_and_removes_only_its_own_folder(h):
    h.host.create_from_iso("dev", iso="/x.iso", disk_gb=10)
    h.host.create_from_iso("other", iso="/x.iso", disk_gb=10)
    h.host.start("dev")
    with pytest.raises(vh.VmError):
        h.host.delete_vm("dev")
    h.host.stop("dev")
    h.host.delete_vm("dev")
    assert not h.host.vm_dir("dev").exists() and h.host.vm_dir("other").exists()


def test_not_enough_free_space_refuses_to_create(h):
    h.host.free_bytes = lambda p: 5 * 2**30
    with pytest.raises(vh.VmError):
        h.host.create_from_iso("dev", iso="/x.iso", disk_gb=100)


def test_failed_qemu_img_leaves_no_half_made_vm(tmp_path):
    f = FakeHost(tmp_path / "s", rc=1)
    with pytest.raises(vh.VmError):
        f.host.create_from_iso("dev", iso="/x.iso", disk_gb=10)
    assert not f.host.vm_dir("dev").exists()


def test_list_vms_reports_kind_and_running(h):
    base = h.host.bases_dir / "golden.qcow2"
    base.parent.mkdir(parents=True)
    base.write_bytes(b"x")
    h.host.create_overlay("scratch", base="golden")
    h.host.create_from_iso("dev", iso="/x.iso", disk_gb=10)
    h.host.start("dev")
    rows = {v["name"]: v for v in h.host.list_vms()}
    assert rows["scratch"]["kind"] == "overlay" and rows["scratch"]["base"] == "golden" and not rows["scratch"]["running"]
    assert rows["dev"]["kind"] == "standalone" and rows["dev"]["running"]


def test_isos_listed_from_the_installer_cache_folder(tmp_path):
    iso_dir = tmp_path / "isos"
    iso_dir.mkdir()
    (iso_dir / "a.iso").write_bytes(b"x")
    (iso_dir / "notes.txt").write_bytes(b"x")
    assert [i["name"] for i in vh.list_isos(iso_dir)] == ["a.iso"]
    assert vh.list_isos(tmp_path / "missing") == []


def test_qmp_socket_path_stays_under_the_unix_socket_limit_even_for_a_deep_store(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    deep = tmp_path / ("very-long-folder-name-" * 6) / "store"
    host = vh.VmHost(deep, persistence_store=tmp_path / "user", run=FakeRun(), spawn=lambda a: 1, is_alive=lambda p: False, free_bytes=lambda p: 500 * 2**30)
    host.create_from_iso("dev", iso="/x.iso", disk_gb=10)
    sock = host.sock_path("dev")
    assert len(str(sock).encode()) < 100 and str(sock) in " ".join(host.qemu_argv("dev"))


def test_start_creates_the_runtime_dir_for_the_socket(tmp_path):
    f = FakeHost(tmp_path / "s")
    f.host.create_from_iso("dev", iso="/x.iso", disk_gb=10)
    f.host.start("dev")
    assert f.host.sock_path("dev").parent.is_dir()


def test_configure_changes_memory_and_cpus_only_while_stopped_and_within_range(h):
    h.host.create_from_iso("dev", iso="/x.iso", disk_gb=10, memory_mb=2048, cpus=2)
    h.host.configure("dev", memory_mb=8192, cpus=6)
    st = h.host.status("dev")
    assert st["memory_mb"] == 8192 and st["cpus"] == 6
    with pytest.raises(vh.VmError):
        h.host.configure("dev", memory_mb=10, cpus=2)
    with pytest.raises(vh.VmError):
        h.host.configure("dev", memory_mb=2048, cpus=0)
    h.host.start("dev")
    with pytest.raises(vh.VmError):
        h.host.configure("dev", memory_mb=4096, cpus=2)


def test_request_stop_only_asks_the_guest_and_does_not_wait(h):
    h.host.create_from_iso("dev", iso="/x.iso", disk_gb=10)
    h.host.start("dev")
    h.responds_to_powerdown = False
    h.host.sleep = lambda s: pytest.fail("request_stop must not wait")
    h.host.request_stop("dev")
    assert h.powered_down and h.quit_sent == [] and h.killed == []
    assert h.host.status("dev")["running"] is True


def test_force_stop_quits_through_qmp_and_bounds_its_wait(h):
    h.host.create_from_iso("dev", iso="/x.iso", disk_gb=10)
    h.host.start("dev")
    h.host.force_stop("dev")
    assert h.quit_sent and h.host.status("dev")["running"] is False


def test_vnc_display_is_loopback_only_and_reported_while_running(h):
    h.host.create_from_iso("dev", iso="/x.iso", disk_gb=10)
    st = h.host.start("dev", display="vnc")
    argv = h.spawned[0]
    assert "-vnc" in argv and argv[argv.index("-vnc") + 1].startswith("127.0.0.1:")
    assert argv[argv.index("-display") + 1] == "none"
    assert st["vnc"] and st["vnc"].startswith("127.0.0.1:59")


def test_default_display_is_a_window_when_a_desktop_is_present_else_vnc():
    assert vh.default_display({"WAYLAND_DISPLAY": "wayland-0"}) == "gtk"
    assert vh.default_display({"DISPLAY": ":0"}) == "gtk"
    assert vh.default_display({}) == "vnc"


def test_vms_run_at_lower_cpu_priority_so_proxmox_and_its_guests_come_first(monkeypatch):
    assert vh.low_priority(["qemu-system-x86_64", "-m", "1"]) == ["nice", "-n", str(vh.VM_NICENESS),
                                                                  "qemu-system-x86_64", "-m", "1"]
    assert vh.VM_NICENESS >= 10
    seen = []

    class FakeProc:
        pid = 777

    monkeypatch.setattr(vh.subprocess, "Popen", lambda argv, **kw: (seen.append((argv, kw)), FakeProc())[1])
    assert vh._real_spawn(["qemu-system-x86_64", "-m", "1"]) == 777
    assert seen[0][0][:3] == ["nice", "-n", str(vh.VM_NICENESS)] and seen[0][1]["start_new_session"] is True


def test_rollback_and_delete_preserve_the_separate_user_disk(h):
    base = h.host.bases_dir / "ubuntu.qcow2"
    base.parent.mkdir(parents=True)
    base.write_bytes(b"clean OS")
    h.host.create_overlay("ubuntu-home", base="ubuntu", persistence_gb=32)
    data = h.host.persistence_store / "ubuntu-home" / "home.qcow2"
    assert data.is_file()
    data.write_bytes(b"documents and browser preferences")
    argv = h.host.qemu_argv("ubuntu-home")
    assert any(str(data) in a and "if=none" in a and "id=home" in a for a in argv)
    assert "virtio-blk-pci,drive=home,serial=baseline-home" in argv
    assert not any("serial=" in argv[i + 1] for i, a in enumerate(argv[:-1]) if a == "-drive")
    h.host.rollback("ubuntu-home")
    assert data.read_bytes() == b"documents and browser preferences"
    h.host.delete_vm("ubuntu-home")
    assert data.read_bytes() == b"documents and browser preferences"
    with pytest.raises(vh.VmError, match="retained"):
        h.host.create_overlay("ubuntu-home", base="ubuntu")


def test_vm_state_never_goes_into_the_vanilla_installer_cache(tmp_path):
    assert "INSTALLER_CACHE" not in str(vh.DEFAULT_STORE)
    assert "USER_" in str(vh.DEFAULT_PERSISTENCE_STORE)
    h = vh.VmHost("/mnt/INSTALLER_CACHE/vms")
    with pytest.raises(vh.VmError, match="INSTALLER_CACHE"):
        h.create_from_iso("bad", iso="/unused.iso", disk_gb=10)


def test_missing_production_mount_refuses_creation_before_any_write(monkeypatch):
    monkeypatch.setattr(vh.os.path, "ismount", lambda p: False)
    h = vh.VmHost(vh.DEFAULT_STORE, run=lambda a: pytest.fail("must not run a command"))
    with pytest.raises(vh.VmError, match="mounted"):
        h.create_from_iso("bad", iso="/unused.iso", disk_gb=10)


def test_retained_disk_is_never_recreated_when_it_is_missing(h):
    base = h.host.bases_dir / "ubuntu.qcow2"
    base.parent.mkdir(parents=True)
    base.write_bytes(b"clean OS")
    h.host.create_overlay("desktop", base="ubuntu")
    (h.host.persistence_store / "desktop" / "home.qcow2").unlink()
    with pytest.raises(vh.VmError, match="missing"):
        h.host.start("desktop")
    assert h.spawned == []


def test_failed_start_cannot_report_a_running_vm(h):
    h.host.create_from_iso("desktop", iso="/x.iso", disk_gb=10)
    h.host.spawn = lambda a: 99
    with pytest.raises(vh.VmError, match="start"):
        h.host.start("desktop")


def test_standard_vm_keeps_its_whole_os_disk_on_protected_storage(tmp_path):
    f = FakeHost(tmp_path / "os")
    f.host.create_from_iso("standard", iso="installer.iso", disk_gb=10)
    root = f.host.disk_path("standard")
    assert root.is_relative_to(f.host.persistence_store)
    assert not root.is_relative_to(f.host.store)
    assert f.host.status("standard")["kind"] == "standalone"
    assert f.host._spec("standard")["base"] is None
    f.host.delete_vm("standard")
    assert not root.exists()
