"""Stopped LXC retained data backups. Add-only destination; restore to a new name.

Includes home/root/data, numeric owners, modes, links, ACLs and user xattrs via GNU tar.
Excludes OS packages/settings, vanilla archives, native base disks and login hashes.
Only same-host, unchanged immutable-base restore is currently supported.
"""
import hashlib
import json
import os
import re
import subprocess
import shutil
import tarfile
import time
import uuid
from pathlib import Path

import offdrive_backup as ob
import drive_admin
import vm_host as vh
import web_gate

ID = re.compile(r'^[0-9a-f]{32}$')
KINDS = ('home','root','data')


def resolve_destination(path, run=None):
    return ob.resolve_destination(path,run=run or ob._default_run,
                                  allowed_serials=drive_admin.ALLOWED_TARGET_SERIALS,
                                  boot_serial=ob._boot_serial() if run is None else None)


def _separate_source(host, dest, run=None):
    runner=run or ob._default_run
    mount=runner(['findmnt','-n','-P','-T',str(host.data_store),'-o','SOURCE'])
    match=re.search(r'SOURCE="(/dev/[^"\n]+)"',mount.stdout)
    if mount.returncode or not match:
        raise vh.VmError('retained source disk cannot be identified')
    ancestry=runner(['lsblk','-s','-l','-n','-o','NAME,TYPE',match.group(1)])
    disks={line.split()[0] for line in ancestry.stdout.splitlines()
           if len(line.split())==2 and line.split()[1]=='disk'}
    if ancestry.returncode or not disks:
        raise vh.VmError('retained source disk ancestry cannot be identified')
    if disks.intersection(dest.disks):
        raise vh.VmError('retained data and backup destination are on the same disk')


def _root(dest):
    root=dest.backup_dir/'container-data'
    if any(p.is_symlink() for p in (root,*root.parents)):
        raise vh.VmError('backup folder is redirected')
    return root


def _digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def _tar(args, *, output=None):
    result=subprocess.run(['tar',*args],stdout=output or subprocess.PIPE,stderr=subprocess.PIPE,timeout=3600)
    if result.returncode:
        raise vh.VmError('native archive operation failed; incomplete state kept, no success inferred')


def _supported_attrs(names):
    if any(not (name.startswith('user.') or name in ('system.posix_acl_access','system.posix_acl_default')) for name in names):
        raise vh.VmError('non-user extended attributes require a verified restore adapter')


def _validate_archive(path, target):
    seen=set();unpacked=0
    with tarfile.open(path,'r:gz') as archive:
        for member in archive:
            _supported_attrs(key.removeprefix('SCHILY.xattr.') for key in member.pax_headers if key.startswith('SCHILY.xattr.'))
            unpacked+=member.size
            parts=Path(member.name).parts
            if not parts or parts[0] not in KINDS or member.name in seen:
                raise vh.VmError('archive contains unexpected or duplicate paths')
            seen.add(member.name)
            try:tarfile.data_filter(member,str(target))
            except tarfile.FilterError as exc:raise vh.VmError('unsafe retained archive entry') from exc
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise vh.VmError('special files cannot be restored')
        if not all(kind in seen for kind in KINDS):
            raise vh.VmError('archive is missing a retained directory')
    return unpacked


def backup(host, *, name, destination: str, run=None, origin=None):
    params={'name':name,'destination':destination}
    web_gate.require(origin,'container_backup',params)
    dest=resolve_destination(destination,run)
    _separate_source(host,dest,run)
    record=host._managed(name)
    if record.get('phase')!='ready' or host.status(name)['running']:
        raise vh.VmError('cleanly shut down a ready container before retained-data backup')
    base=host._config(record['base_vmid']);host._validate_base(record,base)
    source=host.data_path(name,'home').parent
    needed=1024*1024
    for folder,dirs,files in os.walk(source,followlinks=False):
        if Path(folder)!=source and os.path.ismount(folder):
            raise vh.VmError('nested mount requires separate backup coverage')
        _supported_attrs(os.listxattr(folder,follow_symlinks=False))
        for entry in [*dirs,*files]:
            item=Path(folder)/entry
            _supported_attrs(os.listxattr(item,follow_symlinks=False))
            if entry in dirs:continue
            if not item.is_symlink() and not item.is_file():
                raise vh.VmError('special retained files require separate backup coverage')
            needed+=item.lstat().st_size
    ob.check_space(dest,needed_bytes=needed)
    backup_id=uuid.uuid4().hex
    path=_root(dest)/backup_id;path.mkdir(parents=True,mode=0o700)
    (path/'INCOMPLETE.txt').write_text('Manifest absence means incomplete. Baseline never deletes this set.\n')
    os.chmod(path/'INCOMPLETE.txt',0o600)
    archive=path/'retained.tar.gz'
    with archive.open('xb') as stream:
        os.chmod(archive,0o600)
        _tar(['--create','--gzip','--file=-','--numeric-owner','--acls','--xattrs','--sparse',
              '--one-file-system','--directory',str(source),*KINDS],output=stream)
        stream.flush();os.fsync(stream.fileno())
    _validate_archive(archive,path/'validation-only')
    if host._managed(name)!=record or host.status(name)['running'] or host._config(record['base_vmid'])!=base:
        raise vh.VmError('container changed during backup; set remains incomplete')
    manifest={'kind':'baseline-container-retained','version':1,'created':time.time(),
              'backup_id':backup_id,'destination_serial':dest.serial,
              'source':{k:record[k] for k in ('name','vmid','base_vmid','template','os_storage','memory_mb','cpus')},
              'base_config':base,'archive':{'name':archive.name,'sha256':_digest(archive),'bytes':archive.stat().st_size},
              'coverage':{'included':['/home','/root','/data'],
                          'excluded':['OS packages and /etc','immutable base disk and vanilla download','original login hash'],
                          'consistency':'container cleanly stopped','metadata':'numeric owners, modes, symlinks, hard links, POSIX ACLs, user xattrs'}}
    current=resolve_destination(destination,run)
    if (current.serial,current.source,current.path)!=(dest.serial,dest.source,dest.path):
        raise vh.VmError('backup destination changed; set remains incomplete')
    with (path/'MANIFEST.json').open('x') as stream:
        os.chmod(path/'MANIFEST.json',0o600);json.dump(manifest,stream,indent=2);stream.flush();os.fsync(stream.fileno())
    return {'ok':True,'backup_id':backup_id,'message':f'Retained backup {backup_id} verified. OS/base excluded; original kept stopped.'}


def _read(dest, backup_id):
    if not isinstance(backup_id,str) or not ID.fullmatch(backup_id):raise vh.VmError('invalid retained backup ID')
    path=_root(dest)/backup_id
    if path.is_symlink() or (path/'MANIFEST.json').is_symlink() or (path/'retained.tar.gz').is_symlink():
        raise vh.VmError('backup set is redirected')
    manifest=json.loads((path/'MANIFEST.json').read_text())
    if (manifest.get('kind')!='baseline-container-retained' or manifest.get('version')!=1
            or manifest.get('backup_id')!=backup_id or manifest.get('destination_serial')!=dest.serial
            or manifest.get('archive',{}).get('name')!='retained.tar.gz'):
        raise vh.VmError('retained backup identity or manifest changed')
    archive=path/'retained.tar.gz'
    if archive.stat().st_size!=manifest['archive']['bytes'] or _digest(archive)!=manifest['archive']['sha256']:
        raise vh.VmError('retained archive checksum mismatch')
    return manifest,archive


def listing(destination_path, run=None):
    dest=resolve_destination(destination_path,run)
    root=_root(dest)
    result=[]
    for path in sorted(root.iterdir(),reverse=True) if root.is_dir() else []:
        if ID.fullmatch(path.name) and (path/'MANIFEST.json').is_file():
            # Listing checks manifest; restore separately verifies archive bytes.
            if path.is_symlink() or (path/'MANIFEST.json').is_symlink():continue
            manifest=json.loads((path/'MANIFEST.json').read_text())
            if manifest.get('kind')=='baseline-container-retained':result.append(manifest)
    return result


def restore(host, *, name, destination: str, backup_id, run=None, origin=None):
    params={'name':name,'destination':destination,'backup_id':backup_id}
    web_gate.require(origin,'container_restore',params)
    dest=resolve_destination(destination,run)
    _separate_source(host,dest,run)
    manifest,archive=_read(dest,backup_id)
    host._check_data();vh.VmHost._need_name(name)
    if host._record_path(name).exists() or host.data_path(name,'home').parent.exists():
        raise vh.VmError('restore requires a new unused container name; existing data cannot be overwritten')
    source=manifest['source']
    if (not isinstance(source.get('memory_mb'),int) or not 128<=source['memory_mb']<=65536
            or not isinstance(source.get('cpus'),int) or not 1<=source['cpus']<=128
            or not isinstance(source.get('base_vmid'),int) or not 100<=source['base_vmid']<=999999999):
        raise vh.VmError('invalid retained recipe')
    host._validate_base(source,host._config(source['base_vmid']))
    if host._config(source['base_vmid'])!=manifest['base_config']:
        raise vh.VmError('immutable base changed; cross-host/base migration is not implemented')
    target=host.data_path(name,'home').parent
    unpacked=_validate_archive(archive,target)
    if shutil.disk_usage(host.data_store).free < unpacked*1.1+1024*1024:
        raise vh.VmError('not enough space for unpacked retained data; no target allocated')
    # Exclusive new target. Failures leave a visible incomplete reservation; no old resource is deleted.
    password=host.password_factory()
    record={k:source[k] for k in ('base_vmid','template','os_storage','memory_mb','cpus')}
    record.update(name=name,vmid=host._nextid(),phase='restoring',password_hash=host.password_hasher(password))
    host._save(host._record_path(name),record)
    target.mkdir(parents=True,mode=0o700)
    _tar(['--extract','--gzip','--file',str(archive),'--directory',str(target),'--numeric-owner',
          '--same-owner','--acls','--xattrs','--keep-old-files'])
    if _digest(archive)!=manifest['archive']['sha256']:
        raise vh.VmError('archive changed during restore; incomplete target kept stopped')
    for kind in KINDS:
        if not host.data_path(name,kind).is_dir():raise vh.VmError('restored data directory missing')
    host._clone(record)
    return {'ok':True,'name':name,'username':'root','password':password.decode('ascii'),
            'message':'Restored retained state into a new running container; original kept. Save fresh one-time login.'}
