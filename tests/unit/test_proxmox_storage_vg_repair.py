import json
import pytest
from fake_runner import FakeRunner, FakeProc
import single_drive_storage as storage


def runner_for(vg='pve', old_vg_present=False):
    current={'storage':'local-lvm','type':'lvmthin','vgname':vg,'thinpool':'data'}
    class NativeRunner(FakeRunner):
        def run(self, argv, timeout=10):
            self.calls.append(argv)
            if argv[0]=='pvesh': return FakeProc(0,json.dumps(current),'')
            if argv[0]=='vgs': return FakeProc(0,json.dumps({'report':[{'vg':[{'vg_name':'pve'}] if old_vg_present else []}]}),'')
            if argv[0]=='perl': current['vgname']=argv[-1];return FakeProc(0,'','')
            raise AssertionError(argv)
    return NativeRunner()


def bind(monkeypatch):
    monkeypatch.setattr(storage.storage_policy,'verify_runtime',lambda r:{'state':'storage_verified','serial':'DRIVE-A'})
    monkeypatch.setattr(storage,'inspect_target',lambda r,**k:{'vg_name':'baseline_validated','serial':'DRIVE-A'})


def test_repairs_only_missing_installer_default_vg_after_identity_verification(monkeypatch):
    bind(monkeypatch);r=runner_for()
    assert storage.reconcile_proxmox_storage(r)['state']=='native_storage_verified'
    assert r.calls[-1][:2]==['pvesh','get']
    assert any(c[0]=='perl' and c[-1]=='baseline_validated' for c in r.calls)


def test_refuses_to_redirect_storage_that_can_belong_to_another_drive(monkeypatch):
    bind(monkeypatch)
    for r in (runner_for('foreign'),runner_for(old_vg_present=True)):
        with pytest.raises(storage.StorageError):storage.reconcile_proxmox_storage(r)
        assert not any(c[0]=='perl' for c in r.calls)


def test_the_session_temp_storage_and_its_renamed_pool_verify_without_touching_anything(monkeypatch):
    bind(monkeypatch)
    import host_layout
    current = {'storage': host_layout.GUEST_STORAGE, 'type': 'lvmthin', 'vgname': 'baseline_validated', 'thinpool': host_layout.POOL_NAME}

    class Runner(FakeRunner):
        def run(self, argv, timeout=10):
            self.calls.append(argv)
            if argv[:3] == ['pvesh', 'get', f'/storage/{host_layout.GUEST_STORAGE}']:
                return FakeProc(0, json.dumps(current), '')
            raise AssertionError(argv)
    r = Runner()
    assert storage.reconcile_proxmox_storage(r)['state'] == 'native_storage_verified'
    assert not any(c[0] == 'perl' for c in r.calls)
    current['thinpool'] = 'something-else'
    with pytest.raises(storage.StorageError):
        storage.reconcile_proxmox_storage(Runner())
