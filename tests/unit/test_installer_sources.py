import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
import installer_sources as sources


class CacheRunner:
    def __init__(self,root,payload=b'vanilla',label='INSTALLER_CACHE'):
        self.root=root;self.payload=payload;self.label=label;self.downloads=0;self.outputs=[]
    def run(self,argv,timeout=30):
        if argv[0]=='findmnt':return SimpleNamespace(returncode=0,stdout=json.dumps({'filesystems':[{'target':str(self.root),'label':self.label,'uuid':'test-cache-uuid','fstype':'ext4'}]}))
        assert argv[0]=='curl';self.downloads+=1;self.outputs.append(argv[argv.index('--output')+1])
        Path(argv[argv.index('--output')+1]).write_bytes(self.payload)
        return SimpleNamespace(returncode=0,stdout='',stderr='')


def pinned(monkeypatch):
    monkeypatch.setattr(sources.ue,'IMAGE_SHA256',hashlib.sha256(b'vanilla').hexdigest())


def test_plain_directory_or_wrong_role_never_downloads(tmp_path):
    runner=CacheRunner(tmp_path,label='USER_ADMIN')
    with pytest.raises(sources.SourceError,match='INSTALLER_CACHE'):
        sources.acquire_ubuntu(runner,tmp_path)
    assert runner.downloads==0 and list(tmp_path.iterdir())==[]


def test_download_is_vanilla_atomic_and_revalidated_when_already_cached(tmp_path,monkeypatch):
    pinned(monkeypatch);runner=CacheRunner(tmp_path)
    lock=sources.acquire_ubuntu(runner,tmp_path)
    path=Path(lock['path']);assert path.read_bytes()==b'vanilla'
    assert lock['sha256']==hashlib.sha256(b'vanilla').hexdigest()
    assert lock['signature_verified'] is False
    assert sources.acquire_ubuntu(runner,tmp_path)['path']==str(path)
    assert runner.downloads==1
    path.chmod(0o600);path.write_bytes(b'changed')
    with pytest.raises(sources.SourceError,match='digest'):
        sources.acquire_ubuntu(runner,tmp_path)
    assert runner.downloads==1 and path.read_bytes()==b'changed'


def test_bad_download_is_not_published_and_partial_is_removed(tmp_path,monkeypatch):
    pinned(monkeypatch);runner=CacheRunner(tmp_path,payload=b'bad')
    with pytest.raises(sources.SourceError,match='digest'):
        sources.acquire_ubuntu(runner,tmp_path)
    assert list((tmp_path/'isos').iterdir())==[]


def test_preparation_resolves_only_publisher_pinned_actual_cache_sources(tmp_path,monkeypatch):
    pinned(monkeypatch);runner=CacheRunner(tmp_path)
    assert sources.locks(runner,tmp_path)=={}
    sources.acquire_ubuntu(runner,tmp_path)
    assert sources.locks(runner,tmp_path)['ubuntu_base']['sha256']==sources.ue.IMAGE_SHA256


def test_source_subdirectory_cannot_redirect_to_user_storage(tmp_path,monkeypatch):
    pinned(monkeypatch);outside=tmp_path/'retained';outside.mkdir()
    root=tmp_path/'cache';root.mkdir()
    (outside/(sources.ue.BASE_NAME+'.img')).write_bytes(b'vanilla')
    (root/'isos').symlink_to(outside,target_is_directory=True)
    with pytest.raises(sources.SourceError,match='symlink'):
        sources.locks(CacheRunner(root),root)


def test_download_writes_the_open_cache_file_descriptor(tmp_path,monkeypatch):
    pinned(monkeypatch);runner=CacheRunner(tmp_path)
    sources.acquire_ubuntu(runner,tmp_path)
    assert runner.outputs[0].startswith('/proc/') and '/fd/' in runner.outputs[0]
