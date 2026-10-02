"""Real archive/restore I/O; fake Proxmox and drive identities, not boot evidence."""
import json
from pathlib import Path
import pytest
import container_backup as cb
import distro_containers as dc
import web_origin_helper as woh
from test_distro_containers import NativeRunner
from test_offdrive_backup import ScriptedRun as BaseDriveRun, ALLOWED
from types import SimpleNamespace


class ScriptedRun(BaseDriveRun):
    def __init__(self,*args,same_drive=False,**kwargs):
        super().__init__(*args,**kwargs);self.same_drive=same_drive
    def __call__(self,args,timeout=60):
        if not self.same_drive and args[0]=='findmnt' and args[args.index('-T')+1]!=self.mountpoint:
            return SimpleNamespace(returncode=0,stdout='SOURCE="/dev/vda1"\n',stderr='')
        if args[0]=='lsblk' and args[-1]=='/dev/vda1':
            return SimpleNamespace(returncode=0,stdout='vda1 part\nvda disk\n',stderr='')
        return super().__call__(args,timeout)


def setup(tmp_path):
    native=NativeRunner()
    host=dc.DistroContainers(tmp_path/'protected',run=native,run_input=native.input,
                            password_factory=lambda:b'fresh-only',password_hasher=lambda _:'$6$salt$hash')
    host.create('original',template=host.catalog()[0]['name'],cache_storage='source-cache',os_storage='os-thin')
    host.shutdown('original')
    for kind in ('home','root','data'):(host.data_path('original',kind)/'saved').write_text(kind+' retained')
    destination=tmp_path/'separate';destination.mkdir()
    gate=woh.configured_gate()
    return host,native,destination,gate


def origin(gate,action,params):return woh.origin_for('container_'+action,params,gate=gate)


def test_stopped_container_retained_backup_restores_into_new_native_id_and_keeps_original(tmp_path):
    h,native,dest,gate=setup(tmp_path)
    params={'name':'original','destination':str(dest)}
    made=cb.backup(h,**params,run=ScriptedRun(dest),origin=origin(gate,'backup',params))
    restore={'name':'restored','destination':str(dest),'backup_id':made['backup_id']}
    result=cb.restore(h,**restore,run=ScriptedRun(dest),origin=origin(gate,'restore',restore))
    assert result['password']=='fresh-only'
    assert h.status('restored')['running'] and h.status('restored')['vmid']!=h.status('original')['vmid']
    for kind in ('home','root','data'):
        assert (h.data_path('restored',kind)/'saved').read_text()==kind+' retained'
        assert (h.data_path('original',kind)/'saved').read_text()==kind+' retained'
    assert not h.status('original')['running']
    assert not any(a[:2]==['pct','destroy'] for a in native.calls)
    manifest=json.loads((dest/'baseline-backups/container-data'/made['backup_id']/'MANIFEST.json').read_text())
    assert manifest['coverage']['included']==['/home','/root','/data']
    assert manifest['coverage']['excluded']
    assert 'password_hash' not in json.dumps(manifest)


def test_running_container_and_unsigned_backup_cannot_produce_a_complete_set(tmp_path):
    import web_gate
    h,n,dest,gate=setup(tmp_path);params={'name':'original','destination':str(dest)}
    with pytest.raises(web_gate.NotFromWebApp):cb.backup(h,**params,run=ScriptedRun(dest))
    h.start('original')
    with pytest.raises(dc.vh.VmError,match='shut down'):cb.backup(h,**params,run=ScriptedRun(dest),origin=origin(gate,'backup',params))
    assert not (dest/'baseline-backups').exists()


@pytest.mark.parametrize('bad',['existing-name','corrupt-archive','changed-base'])
def test_restore_refuses_before_allocating_or_mutating_any_native_container(tmp_path,bad):
    h,n,dest,gate=setup(tmp_path);params={'name':'original','destination':str(dest)}
    made=cb.backup(h,**params,run=ScriptedRun(dest),origin=origin(gate,'backup',params))
    restore={'name':'original' if bad=='existing-name' else 'new','destination':str(dest),'backup_id':made['backup_id']}
    if bad=='corrupt-archive':
        (dest/'baseline-backups/container-data'/made['backup_id']/'retained.tar.gz').write_bytes(b'corrupt')
    if bad=='changed-base':n.configs[str(h.record('original')['base_vmid'])]['hostname']='unrelated'
    before=len(n.calls)
    with pytest.raises(dc.vh.VmError):cb.restore(h,**restore,run=ScriptedRun(dest),origin=origin(gate,'restore',restore))
    assert not any(a[:2] in (['pct','clone'],['pct','destroy'],['pct','set'],['pct','start']) for a in n.calls[before:])
    assert (h.data_path('original','home')/'saved').read_text()=='home retained'


def test_archive_preserves_numeric_ownership_modes_and_internal_links(tmp_path):
    import os
    h,n,dest,gate=setup(tmp_path)
    saved=h.data_path('original','root')/'saved';os.chmod(saved,0o600)
    (saved.parent/'link').symlink_to('saved');os.link(saved,saved.parent/'hard')
    params={'name':'original','destination':str(dest)}
    made=cb.backup(h,**params,run=ScriptedRun(dest),origin=origin(gate,'backup',params))
    restore={'name':'new','destination':str(dest),'backup_id':made['backup_id']}
    cb.restore(h,**restore,run=ScriptedRun(dest),origin=origin(gate,'restore',restore))
    restored=h.data_path('new','root')/'saved'
    assert restored.stat().st_uid==saved.stat().st_uid and restored.stat().st_mode&0o777==0o600
    assert (restored.parent/'link').readlink()==Path('saved')
    assert (restored.parent/'hard').stat().st_ino==restored.stat().st_ino


def test_restore_refuses_when_retained_store_cannot_fit_the_unpacked_data(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import shutil
    h,n,dest,gate=setup(tmp_path);params={'name':'original','destination':str(dest)}
    made=cb.backup(h,**params,run=ScriptedRun(dest),origin=origin(gate,'backup',params))
    restore={'name':'new','destination':str(dest),'backup_id':made['backup_id']}
    monkeypatch.setattr(shutil,'disk_usage',lambda p:SimpleNamespace(free=0))
    before=len(n.calls)
    with pytest.raises(dc.vh.VmError,match='space'):
        cb.restore(h,**restore,run=ScriptedRun(dest),origin=origin(gate,'restore',restore))
    assert not h._record_path('new').exists()
    assert not any(a[:2]==['pct','clone'] for a in n.calls[before:])


def test_restore_rejects_archive_traversal_even_when_manifest_checksum_matches(tmp_path):
    import io,tarfile,hashlib
    h,n,dest,gate=setup(tmp_path);params={'name':'original','destination':str(dest)}
    made=cb.backup(h,**params,run=ScriptedRun(dest),origin=origin(gate,'backup',params))
    path=dest/'baseline-backups/container-data'/made['backup_id']
    archive=path/'retained.tar.gz'
    with tarfile.open(archive,'w:gz') as out:
        for kind in ('home','root','data'):
            member=tarfile.TarInfo(kind);member.type=tarfile.DIRTYPE;out.addfile(member)
        member=tarfile.TarInfo('home/../../escape');member.size=3;out.addfile(member,io.BytesIO(b'bad'))
    manifest=json.loads((path/'MANIFEST.json').read_text())
    manifest['archive'].update(bytes=archive.stat().st_size,sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
    (path/'MANIFEST.json').write_text(json.dumps(manifest))
    restore={'name':'new','destination':str(dest),'backup_id':made['backup_id']}
    with pytest.raises(dc.vh.VmError,match='unsafe'):cb.restore(h,**restore,run=ScriptedRun(dest),origin=origin(gate,'restore',restore))
    assert not h._record_path('new').exists() and not (tmp_path/'escape').exists()


def test_user_xattr_and_posix_acl_survive_retained_restore(tmp_path):
    import os,struct
    h,n,dest,gate=setup(tmp_path)
    saved=h.data_path('original','root')/'saved'
    os.setxattr(saved,'user.baseline-test',b'retained-xattr')
    acl=struct.pack('<I',2)+b''.join(struct.pack('<HHI',tag,perms,uid) for tag,perms,uid in
        [(1,6,0xffffffff),(2,4,os.getuid()),(4,0,0xffffffff),(16,4,0xffffffff),(32,0,0xffffffff)])
    os.setxattr(saved,'system.posix_acl_access',acl)
    params={'name':'original','destination':str(dest)}
    made=cb.backup(h,**params,run=ScriptedRun(dest),origin=origin(gate,'backup',params))
    restore={'name':'new','destination':str(dest),'backup_id':made['backup_id']}
    cb.restore(h,**restore,run=ScriptedRun(dest),origin=origin(gate,'restore',restore))
    restored=h.data_path('new','root')/'saved'
    assert os.getxattr(restored,'user.baseline-test')==b'retained-xattr'
    assert os.getxattr(restored,'system.posix_acl_access')==acl


def test_backup_refuses_metadata_that_restore_cannot_preserve(tmp_path,monkeypatch):
    import os
    h,n,dest,gate=setup(tmp_path);params={'name':'original','destination':str(dest)}
    monkeypatch.setattr(os,'listxattr',lambda *a,**kw:['security.selinux'])
    with pytest.raises(dc.vh.VmError,match='attributes'):
        cb.backup(h,**params,run=ScriptedRun(dest),origin=origin(gate,'backup',params))
    assert not (dest/'baseline-backups').exists()


def test_destination_identity_change_leaves_an_incomplete_add_only_set(tmp_path,monkeypatch):
    from dataclasses import replace
    h,n,dest,gate=setup(tmp_path);params={'name':'original','destination':str(dest)}
    original=cb.ob.resolve_destination;calls=0
    def changed(*a,**kw):
        nonlocal calls
        calls+=1
        resolved=original(*a,**kw)
        return replace(resolved,serial='different-drive') if calls>1 else resolved
    monkeypatch.setattr(cb.ob,'resolve_destination',changed)
    with pytest.raises(dc.vh.VmError,match='destination changed'):
        cb.backup(h,**params,run=ScriptedRun(dest),origin=origin(gate,'backup',params))
    root=dest/'baseline-backups/container-data'
    assert list(root.glob('*/INCOMPLETE.txt')) and not list(root.glob('*/MANIFEST.json'))



def test_external_retained_data_cannot_be_backed_up_to_the_same_disk(tmp_path):
    h,n,dest,gate=setup(tmp_path);params={'name':'original','destination':str(dest)}
    with pytest.raises(dc.vh.VmError,match='same disk'):
        cb.backup(h,**params,run=ScriptedRun(dest,same_drive=True),origin=origin(gate,'backup',params))
    assert not (dest/'baseline-backups').exists()
