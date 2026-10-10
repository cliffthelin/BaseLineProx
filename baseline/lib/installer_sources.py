"""Vanilla publisher-pinned sources on the actual INSTALLER_CACHE filesystem.

Acquisition is a web job. No guest is created and no storage is provisioned.
HTTPS and the existing publisher SHA256 pin do not imply a detached signature.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import ubuntu_environment as ue


class SourceError(ValueError):
    pass


def cache_identity(runner,root):
    root=Path(root)
    if not root.is_absolute() or root.is_symlink():raise SourceError('INSTALLER_CACHE must be a direct absolute mount path')
    proc=runner.run(['findmnt','--json','--mountpoint',str(root),'-o','TARGET,LABEL,UUID,FSTYPE'],timeout=10)
    try:rows=json.loads(proc.stdout)['filesystems']
    except (ValueError,KeyError,TypeError):rows=[]
    if proc.returncode or len(rows)!=1 or rows[0].get('target')!=str(root) or rows[0].get('label')!='INSTALLER_CACHE' or not rows[0].get('uuid'):
        raise SourceError('The selected path is not an identified mounted INSTALLER_CACHE filesystem; no root-directory fallback')
    return rows[0]


def _source(root):
    folder=Path(root)/'isos'
    if folder.is_symlink():raise SourceError('Installer source directory must not be a symlink')
    return folder/(ue.BASE_NAME+'.img')


def _digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def _lock(path):
    if path.is_symlink() or not path.is_file():raise SourceError('Ubuntu source must be a regular vanilla file')
    if _digest(path)!=ue.IMAGE_SHA256:raise SourceError('Ubuntu source digest mismatch; existing bytes were not replaced')
    return {'path':str(path),'url':ue.IMAGE_URL,'sha256':ue.IMAGE_SHA256,'signature_verified':False}


def locks(runner,root):
    cache_identity(runner,root)
    path=_source(root)
    if path.exists() or path.is_symlink():return {'ubuntu_base':_lock(path)}
    return {}


def acquire_ubuntu(runner,root):
    identity=cache_identity(runner,root);path=_source(root)
    if path.exists() or path.is_symlink():return _lock(path)
    if path.parent.is_symlink():raise SourceError('Installer source directory must not be a symlink')
    path.parent.mkdir(mode=0o700,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.ubuntu-',suffix='.partial',dir=path.parent)
    fresh=Path(temporary)
    try:
        proc=runner.run(['curl','--fail','--location','--proto','=https','--proto-redir','=https','--max-time','300','--retry','2','--output',f'/proc/{os.getpid()}/fd/{fd}',ue.IMAGE_URL],timeout=660)
        if proc.returncode:raise SourceError('Publisher download failed; no source published')
        if cache_identity(runner,root)!=identity:raise SourceError('INSTALLER_CACHE identity changed during download')
        _lock(fresh)
        with fresh.open('rb') as stream:os.fsync(stream.fileno())
        os.chmod(fresh,0o444)
        # Hard-link publication is atomic and cannot overwrite another worker's source.
        try:os.link(fresh,path)
        except FileExistsError:raise SourceError('Source appeared during download; inspect before retrying') from None
        directory=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
        return _lock(path)
    finally:
        try:
            current=fresh.stat();original=os.fstat(fd)
            if (current.st_dev,current.st_ino)==(original.st_dev,original.st_ino):fresh.unlink()
        except FileNotFoundError:pass
        finally:os.close(fd)
