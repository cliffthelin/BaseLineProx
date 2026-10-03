import hashlib
import io
import tarfile
import json
from pathlib import Path
import pytest
import vscode_build as vb
import environment_recipes as er


def settings():return {'format':'baseline.vscode-settings/v1','settings':{'editor.fontSize':18}}

def metadata():
    return {'productVersion':'1.140.0','version':'a'*40,'sha256hash':'b'*64,
            'url':'https://vscode.download.prss.microsoft.com/dbazure/download/stable/'+'a'*40+'/code-stable-x64-123.tar.gz'}


def test_build_binds_settings_to_exact_source_and_refuses_untrusted_metadata():
    build=vb.bind(settings(),metadata())
    assert build['source']['sha256']=='b'*64 and build['settings']==settings()
    assert build['platform']=='linux-x64' and build['format']=='baseline.vscode-build/v1'
    bad=metadata();bad['url']='https://untrusted.invalid/code.tar.gz'
    with pytest.raises(er.RecipeError):vb.bind(settings(),bad)


def test_fetch_checks_actual_bytes_and_never_overwrites(tmp_path):
    payload=b'archive bytes';m=metadata();m['sha256hash']=hashlib.sha256(payload).hexdigest();build=vb.bind(settings(),m)
    class Response(io.BytesIO):
        def geturl(self):return m['url']
    target=tmp_path/'archive'
    vb.fetch(build,target,opener=lambda *a,**k:Response(payload))
    assert target.read_bytes()==payload
    with pytest.raises(er.RecipeError):vb.fetch(build,target,opener=lambda *a,**k:Response(payload))
    with pytest.raises(er.RecipeError):vb.fetch(build,tmp_path/'wrong',opener=lambda *a,**k:Response(b'wrong bytes'))


def test_install_checks_archive_before_creating_new_app_and_profile(tmp_path):
    archive=tmp_path/'source.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        content=b'#!/bin/sh\nexit 0\n';member=tarfile.TarInfo('VSCode-linux-x64/bin/code');member.size=len(content);member.mode=0o755
        tar.addfile(member,io.BytesIO(content))
    m=metadata();m['sha256hash']=hashlib.sha256(archive.read_bytes()).hexdigest();build=vb.bind(settings(),m)
    root=tmp_path/'fresh';result=vb.install(build,archive,root)
    assert Path(result['executable']).is_file()
    assert json.loads((root/'profile/User/settings.json').read_text())=={'editor.fontSize':18}
    assert result['runtime_verified'] is False
    with pytest.raises(er.RecipeError):vb.install(build,archive,root)
    archive.write_bytes(b'bad')
    with pytest.raises(er.RecipeError):vb.install(build,archive,tmp_path/'other')
    assert not (tmp_path/'other').exists()


def test_malicious_archive_is_refused_before_allocating_target(tmp_path):
    archive=tmp_path/'bad.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        member=tarfile.TarInfo('VSCode-linux-x64/../../escape');member.size=1;tar.addfile(member,io.BytesIO(b'x'))
    m=metadata();m['sha256hash']=hashlib.sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(er.RecipeError):vb.install(vb.bind(settings(),m),archive,tmp_path/'target')
    assert not (tmp_path/'target').exists() and not (tmp_path/'escape').exists()


def test_build_cli_validates_lock_and_refuses_modified_private_fields(tmp_path):
    import subprocess
    build=vb.bind(settings(),metadata());path=tmp_path/'build.json';path.write_text(json.dumps(build))
    cli=Path(__file__).resolve().parents[2]/'baseline/bin/baseline-vscode-build'
    result=subprocess.run(['python3',str(cli),'verify',str(path)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    build['private']='must-not-accept';path.write_text(json.dumps(build))
    failed=subprocess.run(['python3',str(cli),'verify',str(path)],capture_output=True,text=True)
    assert failed.returncode!=0 and not failed.stdout
