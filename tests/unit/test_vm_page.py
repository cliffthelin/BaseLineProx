"""The VM library page: everything about VMs is created, configured and run from the browser."""
import pytest

import vm_host as vh
import vm_page as vp
from test_vm_host import FakeHost


@pytest.fixture
def env(tmp_path):
    f = FakeHost(tmp_path / "store")
    iso_dir = tmp_path / "isos"
    iso_dir.mkdir()
    (iso_dir / "ubuntu.iso").write_bytes(b"x")
    return f, iso_dir


def do(env, action, **params):
    f, iso_dir = env
    return vp.perform(f.host, action, params, iso_dir=iso_dir)


def test_create_from_an_iso_in_the_cache_folder(env):
    r = do(env, "create_iso", name="dev", iso="ubuntu.iso", disk_gb="40", memory_mb="4096", cpus="4")
    assert r["ok"] and env[0].host.status("dev")["cpus"] == 4


def test_only_isos_that_are_in_the_cache_folder_can_be_used(env):
    for bad in ("/etc/passwd", "../x.iso", "missing.iso", ""):
        assert not do(env, "create_iso", name="dev", iso=bad, disk_gb="10", memory_mb="2048", cpus="2")["ok"]
    assert env[0].run.calls == []


def test_bad_numbers_and_names_come_back_as_a_message_not_a_crash(env):
    assert not do(env, "create_iso", name="dev", iso="ubuntu.iso", disk_gb="lots", memory_mb="2048", cpus="2")["ok"]
    assert not do(env, "create_iso", name="Bad Name", iso="ubuntu.iso", disk_gb="10", memory_mb="2048", cpus="2")["ok"]
    assert not do(env, "frobnicate", name="dev")["ok"]


def test_destructive_actions_need_confirm(env):
    do(env, "create_iso", name="dev", iso="ubuntu.iso", disk_gb="10", memory_mb="2048", cpus="2")
    assert not do(env, "delete_vm", name="dev")["ok"]
    assert env[0].host.vm_dir("dev").exists()
    assert do(env, "delete_vm", name="dev", confirm="yes")["ok"]
    assert not env[0].host.vm_dir("dev").exists()


def test_rollback_and_freeze_need_confirm_too(env):
    f, _ = env
    do(env, "create_iso", name="dev", iso="ubuntu.iso", disk_gb="10", memory_mb="2048", cpus="2")
    assert not do(env, "freeze", name="dev", base_name="golden")["ok"]
    assert do(env, "freeze", name="dev", base_name="golden", confirm="yes")["ok"]
    do(env, "create_overlay", name="o1", base="golden", memory_mb="2048", cpus="2")
    assert not do(env, "rollback", name="o1")["ok"]
    assert do(env, "rollback", name="o1", confirm="yes")["ok"]


def test_start_stop_configure_through_actions(env):
    do(env, "create_iso", name="dev", iso="ubuntu.iso", disk_gb="10", memory_mb="2048", cpus="2")
    assert do(env, "configure", name="dev", memory_mb="8192", cpus="8")["ok"]
    assert do(env, "start", name="dev", display="vnc")["ok"]
    assert not do(env, "configure", name="dev", memory_mb="4096", cpus="2")["ok"]
    assert do(env, "request_stop", name="dev")["ok"]
    assert do(env, "force_stop", name="dev")["ok"]


def test_the_page_lists_everything_and_escapes_it(env):
    f, iso_dir = env
    do(env, "create_iso", name="dev", iso="ubuntu.iso", disk_gb="10", memory_mb="2048", cpus="2")
    html = vp.render_vms_page(store=str(f.host.store), free_gb=321, kvm_ok=True, isos=vh.list_isos(iso_dir),
                              bases=f.host.list_bases(), vms=f.host.list_vms(), notice='<script>alert(1)</script>',
                              notice_ok=False, default_display="gtk").decode()
    assert "<body>" in html and "dev" in html and "ubuntu.iso" in html and "321" in html
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;alert(1)" in html
    assert "/vms/action" in html


def test_the_page_says_so_when_kvm_is_not_usable(env):
    f, iso_dir = env
    html = vp.render_vms_page(store=str(f.host.store), free_gb=1, kvm_ok=False, isos=[], bases=[], vms=[],
                              notice="", notice_ok=None, default_display="vnc").decode()
    assert "KVM" in html and "not available" in html.lower()


def test_store_location_must_be_an_absolute_clean_path(tmp_path):
    cfg = tmp_path / "vm-config.json"
    assert vp.load_store(cfg, default="/d") == "/d"
    assert vp.save_store(cfg, str(tmp_path / "vms"))["ok"]
    assert vp.load_store(cfg, default="/d") == str(tmp_path / "vms")
    for bad in ("relative/path", "/a/../b", "", "/dev/sdb", "/proc/x", "/sys/x", "/etc"):
        assert not vp.save_store(cfg, bad)["ok"]


def test_ubuntu_can_be_created_and_rebuilt_from_the_web_action(env):
    f, _ = env
    f.host.bases_dir.mkdir(parents=True)
    import ubuntu_environment as ue
    (f.host.base_path(ue.BASE_NAME)).write_bytes(b"clean Ubuntu")
    r = do(env, "create_ubuntu", name="desktop", recipe="ubuntu-desktop", disk_gb="40",
           persistence_gb="32", memory_mb="4096", cpus="2", homepage="https://baseline.invalid:8006")
    assert r["ok"] and r["username"] == "baseline-admin" and len(r["password"]) >= 32
    data = f.host.persistence_path("desktop")
    data.write_bytes(b"my preferences")
    assert do(env, "rollback", name="desktop", confirm="yes")["ok"]
    assert data.read_bytes() == b"my preferences"
    assert b"mkfs" not in (f.host.vm_dir("desktop") / "seed" / "user-data").read_bytes()


def test_ubuntu_form_and_one_time_login_are_available_without_leaking_in_url(env):
    f, _ = env
    page = vp.render_vms_page(store=str(f.host.store), free_gb=10, kvm_ok=True, isos=[],
                              bases=[], vms=[], notice="", notice_ok=None, default_display="vnc").decode()
    assert "create_ubuntu" in page and "prepare_ubuntu" in page
    assert "ubuntu-desktop" in page and "ubuntu-server" in page
    assert 'name="persistence_gb"' in page and 'name="homepage"' in page
    assert 'id="one-time-login"' in page
    assert "j.password" in page and "textContent" in page
    assert "sessionStorage" not in page and "localStorage" not in page


def test_proxmox_page_does_not_offer_a_parallel_qemu_window(env):
    f, _ = env
    page = vp.render_vms_page(store=str(f.host.store), persistence_store=str(f.host.persistence_store),
                              backend="Proxmox", free_gb=10, kvm_ok=True, isos=[], bases=[],
                              vms=[], notice="", notice_ok=None, default_display="vnc").decode()
    assert "Proxmox" in page and "Open Proxmox" in page
    assert "low CPU priority" not in page and "windows open" not in page


def test_external_os_and_user_storage_can_be_selected_independently(tmp_path):
    cfg = tmp_path / "config.json"
    result = vp.save_store(cfg, str(tmp_path / "external-os"), persistence_store=str(tmp_path / "external-user"))
    assert result["ok"]
    assert vp.load_persistence_store(cfg, default="/default") == str(tmp_path / "external-user")
    assert not vp.save_store(cfg, str(tmp_path / "external-os"), persistence_store="/mnt/INSTALLER_CACHE/data")["ok"]
    assert vp.load_persistence_store(cfg, default="/default") == str(tmp_path / "external-user")


def test_guest_homepage_is_supplied_by_the_host_even_when_the_browser_is_local(env):
    f, _ = env
    page = vp.render_vms_page(store=str(f.host.store), free_gb=10, kvm_ok=True, isos=[],
                              bases=[], vms=[], notice="", notice_ok=None, default_display="vnc",
                              homepage="https://192.168.20.5:8006").decode()
    assert 'name="homepage"' in page and 'value="https://192.168.20.5:8006"' in page


def test_requested_distros_are_shown_with_honest_vm_and_emulator_status():
    page = vp.render_vms_page(store='/os', free_gb=20, kvm_ok=True, isos=[], bases=[], vms=[],
                             notice='', notice_ok=None, default_display='vnc').decode()
    for name in ('SparkyLinux', 'MX Linux', 'Zorin OS', 'Bazzite', 'CachyOS', 'Omarchy', 'OpenMediaVault', 'ChromeOS', 'GrapheneOS'):
        assert name in page
    assert 'Not installed or boot-verified by Baseline' in page
    assert 'development emulator' in page
    assert 'NAS data disks' in page
    assert 'not automatically mounted' in page


def test_iso_creation_can_select_uefi_for_desktop_installers(env):
    result = do(env, 'create_iso', name='desktop', iso='ubuntu.iso', disk_gb='40', memory_mb='4096', cpus='2', firmware='uefi')
    assert result['ok']
    assert env[0].host._spec('desktop')['uefi'] is True


def test_overlay_creation_honors_requested_retained_disk_size(env):
    do(env, 'create_iso', name='gold', iso='ubuntu.iso', disk_gb='40', memory_mb='4096', cpus='2')
    assert do(env, 'freeze', name='gold', base_name='installed', confirm='yes')['ok']
    assert do(env, 'create_overlay', name='desktop', base='installed', memory_mb='4096', cpus='2', persistence_gb='64')['ok']
    assert env[0].host._spec('desktop')['persistence_gb'] == 64
