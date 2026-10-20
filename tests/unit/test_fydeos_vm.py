"""FydeOS needs early modules, virgl, and a retained whole-system disk."""
import pytest
import vm_host as vh
from test_vm_host import FakeHost


def test_early_modules_are_loaded_before_udev_graphics_events():
    import fydeos_vm as f
    original='start on started udev-boot\ntask\nscript\n  udevadm trigger --action=add\nend script\n'
    patched=f.early_modules(original)
    assert patched.index('modprobe virtio_gpu') < patched.index('udevadm trigger')
    assert 'modprobe virtio_net' in patched
    assert f.early_modules(patched)==patched
    with pytest.raises(ValueError):f.early_modules('unexpected layout')


def test_fydeos_account_state_is_in_retained_root_and_rollback_refuses(tmp_path):
    h=FakeHost(tmp_path/'os').host
    h.bases_dir.mkdir(parents=True)
    h.base_path('fydeos-base').write_bytes(b'synthetic base')
    spec=h.create_retained_base('fyde',base='fydeos-base',graphics='virgl')
    assert spec['root_disk']==str(h.standalone_path('fyde'))
    assert not spec.get('base') and spec['source_base']=='fydeos-base'
    assert spec['graphics']=='virgl'
    argv=h.qemu_argv('fyde',display='vnc')
    assert 'virtio-vga-gl' in argv
    assert 'egl-headless,rendernode=/dev/dri/renderD128' in argv
    with pytest.raises(vh.VmError,match='standalone'):
        h.rollback('fyde')


def test_raw_patch_rejects_device_paths_and_unknown_partition_maps(tmp_path):
    import fydeos_vm as f
    with pytest.raises(ValueError):f.patch_raw('/dev/zero', tmp_path)
    raw=tmp_path/'bad.raw';raw.write_bytes(b'not a GPT disk')
    with pytest.raises(ValueError,match='GPT'):f.patch_raw(raw,tmp_path)


def test_legacy_fydeos_manifest_is_refused_before_install(tmp_path):
    import json
    import prebuilt_environment as p
    (tmp_path/'fydeos-base.json').write_text(json.dumps({'holds_install_state_or_secrets':False}))
    with pytest.raises(p.PrebuiltError,match='VirtIO'):
        p.read_manifest(tmp_path,'fydeos')


def test_proxmox_uses_virgl_and_protected_storage_for_fydeos(tmp_path):
    from test_proxmox_vm_host import host
    h,run=host(tmp_path)
    h.base_path('fydeos-base').write_bytes(b'synthetic')
    h.create_retained_base('fyde',base='fydeos-base',graphics='virgl')
    assert run.config['vga']=='virtio-gl'
    assert run.config['sata0'].startswith(__import__('proxmox_vm_host').USER_STORAGE + ':')


def test_fydeos_uses_the_rehearsed_sata_and_e1000_devices(tmp_path):
    h=FakeHost(tmp_path/'os').host
    h.bases_dir.mkdir(parents=True)
    h.base_path('fydeos-base').write_bytes(b'synthetic')
    h.create_retained_base('fyde',base='fydeos-base',graphics='virgl')
    argv=h.qemu_argv('fyde',display='vnc')
    assert 'e1000,netdev=n0' in argv
    assert 'ide-hd,drive=fydeos-root,bus=fydeos-ahci.0' in argv


def test_retirement_checks_the_exact_fydeos_sata_attachment(tmp_path):
    import proxmox_vm_host as p
    from test_proxmox_vm_host import host
    h,run=host(tmp_path)
    h.base_path('fydeos-base').write_bytes(b'synthetic')
    spec=h.create_retained_base('fyde',base='fydeos-base',graphics='virgl')
    record=h._record('fyde')
    assert p.retirement_volumes('fyde',spec,record,run.config)[0]==run.config['sata0']
    with pytest.raises(vh.VmError,match='additional'):
        p.retirement_volumes('fyde',spec,record,dict(run.config,virtio0='foreign:disk'))


def test_custom_fydeos_base_is_found_on_appdata_without_changing_other_os_sources(tmp_path,monkeypatch):
    import prebuilt_environment as p
    custom=tmp_path/'APPDATA_ADMIN/os-bases'
    custom.mkdir(parents=True)
    (custom/'fydeos-base.json').write_text('{}')
    monkeypatch.setattr(p,'FYDEOS_BASES_DIR',custom)
    legacy='/mnt/INSTALLER_CACHE/installer/expanded/baseline-cache/os-bases'
    assert p.source_for('fydeos',legacy)==custom
    assert str(p.source_for('debian',legacy))==legacy
