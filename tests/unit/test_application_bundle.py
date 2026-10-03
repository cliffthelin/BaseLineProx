import json
from pathlib import Path
import pytest
import environment_recipes as er


def test_capture_configuration_is_portable_and_unknown_content_is_excluded():
    import application_bundle as ab
    result=ab.capture('vscode',json.dumps({'editor.fontSize':18,'private.token':'exclude'}))
    assert result['configuration']=={'editor.fontSize':18}
    assert result['excluded_count']==1
    chrome=ab.capture('chrome',json.dumps({'homepage':'https://127.0.0.1:8006','cookies':['secret']}))
    assert chrome['configuration']=={'homepage':'https://127.0.0.1:8006'}
    for app in ('spotify','chatgpt','claude'):
        assert ab.capture(app,json.dumps({'scale':1.25,'token':'secret'}))['configuration']=={'scale':1.25}
    with pytest.raises(er.RecipeError):ab.capture('unknown','{}')


def test_recipe_locks_exact_bytes_and_refuses_unsupported_platform_and_sources():
    import application_bundle as ab
    source={'url':'https://persistent.oaistatic.com/codex-app-prod/linux/deb/latest/chatgpt_amd64.deb',
            'sha256':'a'*64,'version':'26.930.31730','package':'chatgpt','medium':'deb'}
    recipe=ab.bind('chatgpt',{'scale':1.25},source,{'os':'ubuntu','release':'24.04','arch':'amd64'})
    assert ab.validate(recipe)==recipe
    for change in ({'platform':{'os':'windows','release':'11','arch':'amd64'}}, {'private':'secret'}):
        with pytest.raises(er.RecipeError):ab.validate({**recipe,**change})
    with pytest.raises(er.RecipeError):ab.bind('chatgpt',{'token':'secret'},source,recipe['platform'])
    with pytest.raises(er.RecipeError):ab.bind('chatgpt',{},dict(source,url='https://evil.invalid/app.deb'),recipe['platform'])


def test_fresh_install_reuses_only_matching_private_state_and_checks_bytes(tmp_path):
    import application_bundle as ab
    import subprocess,hashlib
    pkg=tmp_path/'pkg';(pkg/'DEBIAN').mkdir(parents=True);(pkg/'DEBIAN').chmod(0o755)
    (pkg/'DEBIAN/control').write_text('Package: chatgpt\nVersion: 1.0\nArchitecture: amd64\nMaintainer: test\nDescription: synthetic test package\n')
    exe=pkg/'usr/lib/chatgpt/ChatGPT';exe.parent.mkdir(parents=True);exe.write_text('#!/bin/sh\nexit 0\n');exe.chmod(0o755)
    archive=tmp_path/'app.deb';subprocess.run(['dpkg-deb','--build',str(pkg),str(archive)],check=True,capture_output=True)
    source={'url':'https://persistent.oaistatic.com/codex-app-prod/linux/deb/latest/chatgpt_amd64.deb',
            'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'version':'1.0','package':'chatgpt','medium':'deb'}
    recipe=ab.bind('chatgpt',{'scale':1.25},source,{'os':'ubuntu','release':'26.04','arch':'amd64'})
    data=tmp_path/'private';first=ab.install(recipe,archive,tmp_path/'first',data)
    note=data/'home/note';note.write_text('retained')
    second=ab.install(recipe,archive,tmp_path/'second',data)
    assert Path(second['executable']).is_file() and note.read_text()=='retained'
    assert first['runtime_verified'] is False and second['retained_identity']==first['retained_identity']
    with pytest.raises(er.RecipeError):ab.install(recipe,archive,tmp_path/'first',data)
    archive.write_bytes(b'corrupt')
    with pytest.raises(er.RecipeError):ab.install(recipe,archive,tmp_path/'third',data)
    assert not (tmp_path/'third').exists()


def test_prepare_resolves_publisher_metadata_and_verifies_download(tmp_path):
    import application_bundle as ab
    import subprocess,hashlib,io
    pkg=tmp_path/'pkg';(pkg/'DEBIAN').mkdir(parents=True);(pkg/'DEBIAN').chmod(0o755)
    (pkg/'DEBIAN/control').write_text('Package: spotify-client\nVersion: 1.2.3\nArchitecture: amd64\nMaintainer: test\nDescription: test\n')
    source=tmp_path/'source.deb';subprocess.run(['dpkg-deb','--build',str(pkg),str(source)],check=True,capture_output=True)
    payload=source.read_bytes();sha=hashlib.sha256(payload).hexdigest()
    metadata=f'Package: spotify-client\nVersion: 1.2.3\nArchitecture: amd64\nFilename: pool/non-free/s/spotify-client/spotify-client_1.2.3_amd64.deb\nSHA256: {sha}\n\n'.encode()
    class Response(io.BytesIO):
        def __init__(self,url):super().__init__(metadata if url.endswith('/Packages') else payload);self.url=url
        def geturl(self):return self.url
    result=ab.prepare('spotify',{'scale':1.25},tmp_path/'downloads',platform={'os':'debian','release':'13','arch':'amd64'},opener=lambda url,**kw:Response(url))
    assert result['recipe']['source']['sha256']==sha
    assert Path(result['archive']).read_bytes()==payload
    with pytest.raises(er.RecipeError):ab.prepare('spotify',{},tmp_path/'downloads',platform=result['recipe']['platform'],opener=lambda url,**kw:Response(url))


def test_sandbox_command_hides_other_profiles_and_requires_explicit_sharing(tmp_path):
    import application_bundle as ab
    generation=tmp_path/'generation';generation.mkdir();data=tmp_path/'private';data.mkdir();(data/'home').mkdir()
    exchange=tmp_path/'exchange';exchange.mkdir()
    command=ab.sandbox_command(generation,data,['/bin/true'],environment={})
    assert '--ro-bind' in command and str(data/'home') in command
    assert '--bind' in command and '/home/baseline' in command
    assert str(exchange) not in command
    shared=ab.sandbox_command(generation,data,['/bin/true'],environment={},shared=exchange)
    assert ['--bind',str(exchange),'/exchange'] == shared[shared.index(str(exchange))-1:shared.index(str(exchange))+2]
    with pytest.raises(er.RecipeError):ab.sandbox_command(generation,data,['/bin/true'],environment={},shared=data)


def test_cli_capture_and_validate_do_not_publish_excluded_values(tmp_path):
    import subprocess
    cli=Path(__file__).resolve().parents[2]/'baseline/bin/baseline-apps'
    source=tmp_path/'settings.json';source.write_text('{"scale":1.25,"token":"never-output"}')
    result=subprocess.run(['python3',str(cli),'capture','spotify',str(source)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert 'never-output' not in result.stdout and json.loads(result.stdout)['excluded_count']==1


def test_deb_system_links_do_not_escape_or_break_native_payload_install(tmp_path):
    import application_bundle as ab
    import subprocess,hashlib
    pkg=tmp_path/'pkg';(pkg/'DEBIAN').mkdir(parents=True);(pkg/'DEBIAN').chmod(0o755)
    (pkg/'DEBIAN/control').write_text('Package: google-chrome-stable\nVersion: 1.0\nArchitecture: amd64\nMaintainer: test\nDescription: test\n')
    binary=pkg/'opt/google/chrome/chrome';binary.parent.mkdir(parents=True);binary.write_text('#!/bin/sh\nexit 0\n');binary.chmod(0o755)
    link=pkg/'etc/cron.daily/google-chrome';link.parent.mkdir(parents=True);link.symlink_to('/opt/google/chrome/cron/google-chrome')
    archive=tmp_path/'chrome.deb';subprocess.run(['dpkg-deb','--build',str(pkg),str(archive)],check=True,capture_output=True)
    source={'url':'https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_1.0_amd64.deb','sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'version':'1.0','package':'google-chrome-stable','medium':'deb'}
    recipe=ab.bind('chrome',{},source,ab.target_platform())
    result=ab.install(recipe,archive,tmp_path/'generation',tmp_path/'data')
    assert Path(result['executable']).is_file()
    assert not (tmp_path/'generation/root/etc').exists()


def test_sandbox_preflight_reports_nested_namespace_failure_without_success(tmp_path):
    import application_bundle as ab
    generation=tmp_path/'generation';generation.mkdir();data=tmp_path/'private';data.mkdir();(data/'home').mkdir()
    import subprocess
    class Runner:
        def __call__(self,argv,**kwargs):return subprocess.CompletedProcess(argv,1,'','uid mapping refused')
    report=ab.sandbox_preflight(generation,data,run=Runner())
    assert report['usable'] is False
    assert report['inner_sandbox']=='nested user namespace mapping unavailable'


def test_stopped_state_backup_restores_into_new_identity_checked_path(tmp_path):
    import application_bundle as ab
    data=tmp_path/'private';data.mkdir();home=data/'home';home.mkdir();(home/'note').write_text('retained')
    (data/'IDENTITY.json').write_text(json.dumps({'format':'baseline.app-state/v1','app':'spotify','id':'a'*32}))
    backup=ab.backup_state(data,tmp_path/'backup.tar')
    restored=ab.restore_state(tmp_path/'backup.tar',backup,tmp_path/'restored')
    assert (tmp_path/'restored/home/note').read_text()=='retained'
    assert restored['id']=='a'*32 and (home/'note').read_text()=='retained'
    with pytest.raises(er.RecipeError):ab.restore_state(tmp_path/'backup.tar',backup,data)
    (tmp_path/'backup.tar').write_bytes(b'corrupt')
    with pytest.raises(er.RecipeError):ab.restore_state(tmp_path/'backup.tar',backup,tmp_path/'other')
    assert not (tmp_path/'other').exists()


def test_runtime_install_plan_scopes_namespace_helper_without_global_sysctl():
    import application_bundle as ab
    plan=ab.runtime_plan({'os':'ubuntu','release':'24.04','arch':'amd64'})
    assert plan['helper']=='/opt/baseline/libexec/baseline-app-bwrap'
    assert 'userns,' in plan['apparmor_profile']
    assert 'sysctl' not in json.dumps(plan) and '--no-sandbox' not in json.dumps(plan)
    assert 'bubblewrap' in plan['packages'] and 'libgtk-3-0' in plan['packages']
    with pytest.raises(er.RecipeError):ab.runtime_plan({'os':'windows','release':'11','arch':'amd64'})


def test_cli_exposes_runtime_prerequisites_and_private_backup_restore(tmp_path):
    import subprocess
    cli=Path(__file__).resolve().parents[2]/'baseline/bin/baseline-apps'
    plan=subprocess.run(['python3',str(cli),'runtime-plan'],capture_output=True,text=True)
    assert plan.returncode==0,plan.stderr
    assert json.loads(plan.stdout)['helper'].endswith('baseline-app-bwrap')
    data=tmp_path/'private';data.mkdir();(data/'home').mkdir();(data/'home/note').write_text('test')
    (data/'IDENTITY.json').write_text(json.dumps({'format':'baseline.app-state/v1','app':'vscode','id':'a'*32}))
    archive=tmp_path/'state.tar';manifest=tmp_path/'manifest.json'
    saved=subprocess.run(['python3',str(cli),'backup',str(data),str(archive)],capture_output=True,text=True)
    assert saved.returncode==0,saved.stderr
    manifest.write_text(saved.stdout)
    restored=subprocess.run(['python3',str(cli),'restore',str(manifest),str(archive),str(tmp_path/'restored')],capture_output=True,text=True)
    assert restored.returncode==0,restored.stderr
    assert (tmp_path/'restored/home/note').read_text()=='test'


def test_explicit_network_proxy_is_validated_and_not_taken_from_recipe_content(tmp_path):
    import application_bundle as ab
    generation=tmp_path/'generation';generation.mkdir();data=tmp_path/'private';data.mkdir();(data/'home').mkdir()
    command=ab.sandbox_command(generation,data,['/bin/true'],environment={},proxy='http://10.0.2.100:3128')
    assert ['--setenv','HTTPS_PROXY','http://10.0.2.100:3128'] == command[command.index('HTTPS_PROXY')-1:command.index('HTTPS_PROXY')+2]
    with pytest.raises(er.RecipeError):ab.sandbox_command(generation,data,['/bin/true'],environment={},proxy='http://user:secret@example.com')


def test_backup_refuses_running_profile_before_enumerating_private_files(tmp_path,monkeypatch):
    import application_bundle as ab
    import fcntl
    data=tmp_path/'private';data.mkdir();(data/'home').mkdir()
    (data/'IDENTITY.json').write_text(json.dumps({'format':'baseline.app-state/v1','app':'spotify','id':'a'*32}))
    def unexpected_scan(*args,**kwargs):
        raise AssertionError('private files scanned before stopped-state lock')
    monkeypatch.setattr(Path,'rglob',unexpected_scan)
    with (data/'RUN.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(er.RecipeError,match='stop application'):
            ab.backup_state(data,tmp_path/'backup.tar')
    assert not (tmp_path/'backup.tar').exists()


def test_stopped_backup_omits_ephemeral_socket_but_refuses_fifo(tmp_path,monkeypatch):
    import application_bundle as ab
    import socket,os,tarfile
    data=tmp_path/'private';data.mkdir();home=data/'home';home.mkdir()
    (data/'IDENTITY.json').write_text(json.dumps({'format':'baseline.app-state/v1','app':'vscode','id':'a'*32}))
    monkeypatch.chdir(home)  # AF_UNIX addresses are bounded even when pytest's root is long.
    sock=socket.socket(socket.AF_UNIX);sock.bind('ipc.sock');sock.close()
    manifest=ab.backup_state(data,tmp_path/'backup.tar')
    assert 'sockets omitted' in manifest['coverage']
    with tarfile.open(tmp_path/'backup.tar') as tar:assert 'home/ipc.sock' not in tar.getnames()
    os.mkfifo(home/'pipe')
    with pytest.raises(er.RecipeError,match='special file'):ab.backup_state(data,tmp_path/'other.tar')


def test_chatgpt_backup_omits_regenerated_codex_tmp_links_preserves_config(tmp_path):
    import application_bundle as ab
    import tarfile
    data=tmp_path/'private';data.mkdir();home=data/'home';(home/'.codex/tmp/arg0').mkdir(parents=True)
    (data/'IDENTITY.json').write_text(json.dumps({'format':'baseline.app-state/v1','app':'chatgpt','id':'a'*32}))
    (home/'.codex/tmp/arg0/apply_patch').symlink_to('/app/root/usr/lib/chatgpt/resources/codex')
    (home/'.codex/config.toml').write_text('synthetic configuration')
    ab.backup_state(data,tmp_path/'backup.tar')
    with tarfile.open(tmp_path/'backup.tar') as tar:
        assert 'home/.codex/config.toml' in tar.getnames()
        assert not any(n.startswith('home/.codex/tmp') for n in tar.getnames())
    (home/'external').symlink_to('/etc/passwd')
    with pytest.raises(er.RecipeError,match='external profile symlink'):ab.backup_state(data,tmp_path/'other.tar')


def test_install_refuses_insufficient_space_before_allocating_profile(tmp_path,monkeypatch):
    import application_bundle as ab
    import shutil
    from types import SimpleNamespace
    import tarfile,hashlib
    payload=tmp_path/'payload';payload.write_text('#!/bin/sh\nexit 0\n');payload.chmod(0o755)
    archive=tmp_path/'code.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:tar.add(payload,arcname='VSCode-linux-x64/code')
    source={'url':'https://vscode.download.prss.microsoft.com/dbazure/download/stable/'+('a'*40)+'/code-stable-x64-1.tar.gz','sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'version':'1.0','package':'code','medium':'tar.gz'}
    recipe=ab.bind('vscode',{},source,ab.target_platform())
    monkeypatch.setattr(shutil,'disk_usage',lambda path:SimpleNamespace(free=0))
    with pytest.raises(er.RecipeError,match='space'):
        ab.install(recipe,archive,tmp_path/'generation',tmp_path/'data')
    assert not (tmp_path/'generation').exists() and not (tmp_path/'data').exists()


def test_publisher_transport_identifies_baseline_instead_of_default_python_agent(monkeypatch):
    import application_bundle as ab
    import urllib.request
    seen=[]
    monkeypatch.setattr(urllib.request,'urlopen',lambda request,timeout:seen.append((request,timeout)) or 'response')
    assert ab.publisher_open('https://persistent.oaistatic.com/codex-app-prod/linux/deb/latest/chatgpt_amd64.deb',timeout=30)=='response'
    request,timeout=seen[0]
    assert request.get_header('User-agent').startswith('BaselineOS/') and timeout==30
    assert request.full_url.startswith('https://persistent.oaistatic.com/')


def test_launch_supplies_a_private_dbus_session_without_host_service_activation(tmp_path,monkeypatch):
    import application_bundle as ab
    import tarfile,hashlib,subprocess
    payload=tmp_path/'payload';payload.write_text('#!/bin/sh\nexit 0\n');payload.chmod(0o755)
    archive=tmp_path/'code.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:tar.add(payload,arcname='VSCode-linux-x64/code')
    source={'url':'https://vscode.download.prss.microsoft.com/dbazure/download/stable/'+('a'*40)+'/code-stable-x64-1.tar.gz','sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'version':'1.0','package':'code','medium':'tar.gz'}
    recipe=ab.bind('vscode',{},source,ab.target_platform());generation=tmp_path/'generation';data=tmp_path/'private'
    ab.install(recipe,archive,generation,data)
    config=(generation/'DBUS-SESSION.conf').read_text()
    assert '<listen>unix:tmpdir=/tmp</listen>' in config
    assert 'servicedir' not in config
    seen=[]
    monkeypatch.setattr(subprocess,'run',lambda argv,**kw:seen.append(argv) or subprocess.CompletedProcess(argv,0))
    assert ab.launch(generation,data)==0
    assert '/usr/bin/dbus-run-session' in seen[0] and '/app/DBUS-SESSION.conf' in seen[0]
    assert not any('/run/user/' in str(arg) and 'bus' in str(arg) for arg in seen[0])


def test_managed_capture_extracts_native_homepage_without_opaque_profile_content(tmp_path):
    import application_bundle as ab
    generation=tmp_path/'generation';generation.mkdir();data=tmp_path/'private';data.mkdir()
    home=data/'home';prefs=home/'.config/google-chrome/Default/Preferences';prefs.parent.mkdir(parents=True)
    prefs.write_text(json.dumps({'homepage':'https://pve.example:8006','account_token':'must-stay-private'}))
    source={'url':'https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_1.0_amd64.deb','sha256':'a'*64,'version':'1.0','package':'google-chrome-stable','medium':'deb'}
    recipe=ab.bind('chrome',{'scale':1.25},source,ab.target_platform())
    (generation/'BUILD.json').write_text(ab.export(recipe));(generation/'INSTALL.json').write_text(json.dumps({'retained_identity':'a'*32,'recipe_digest':ab.digest(recipe)}))
    (data/'IDENTITY.json').write_text(json.dumps({'format':'baseline.app-state/v1','app':'chrome','id':'a'*32}))
    result=ab.capture_installed(generation,data)
    assert result['recipe']['configuration']=={'scale':1.25,'homepage':'https://pve.example:8006'}
    assert result['coverage']=='native allowlisted configuration plus Baseline launch options'
    assert 'must-stay-private' not in json.dumps(result) and result['runtime_verified'] is False
    import fcntl
    with (data/'RUN.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(er.RecipeError,match='stop application'):ab.capture_installed(generation,data)


def test_chrome_profile_flag_does_not_open_private_directory_as_a_file_url(tmp_path,monkeypatch):
    import application_bundle as ab
    import subprocess
    generation=tmp_path/'generation';generation.mkdir();data=tmp_path/'private';data.mkdir();(data/'home').mkdir()
    source={'url':'https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_1.0_amd64.deb','sha256':'a'*64,'version':'1.0','package':'google-chrome-stable','medium':'deb'}
    recipe=ab.bind('chrome',{},source,ab.target_platform())
    (generation/'BUILD.json').write_text(ab.export(recipe));(generation/'INSTALL.json').write_text(json.dumps({'retained_identity':'a'*32,'recipe_digest':ab.digest(recipe)}))
    (generation/'DBUS-SESSION.conf').write_text(ab.PRIVATE_DBUS_CONFIG)
    (data/'IDENTITY.json').write_text(json.dumps({'format':'baseline.app-state/v1','app':'chrome','id':'a'*32}))
    prefs=data/'home/.config/google-chrome/Default/Preferences';prefs.parent.mkdir(parents=True)
    prefs.write_text(json.dumps({'homepage':'https://10.0.2.102:8006','profile':{'exit_type':'Crashed'}}))
    seen=[];monkeypatch.setattr(subprocess,'run',lambda argv,**kw:seen.append(argv) or subprocess.CompletedProcess(argv,0))
    assert ab.launch(generation,data)==0
    assert 'https://10.0.2.102:8006' in seen[0]
    assert '--user-data-dir=/home/baseline/.config/google-chrome' in seen[0]
    assert '/home/baseline/.config/google-chrome' not in seen[0]


def test_reviewed_native_apply_preserves_other_chrome_preferences_and_refuses_live_profile(tmp_path):
    import application_bundle as ab
    import fcntl
    data=tmp_path/'private';data.mkdir();prefs=data/'home/.config/google-chrome/Default/Preferences';prefs.parent.mkdir(parents=True)
    (data/'IDENTITY.json').write_text(json.dumps({'format':'baseline.app-state/v1','app':'chrome','id':'a'*32}))
    prefs.write_text(json.dumps({'homepage':'https://old.example','secret':'retain-private','session':{'private_native_setting':True}}))
    result=ab.apply_configuration(data,{'homepage':'https://pve.example:8006'})
    updated=json.loads(prefs.read_text())
    assert updated['homepage']=='https://pve.example:8006' and updated['secret']=='retain-private'
    assert updated['session']['private_native_setting'] is True
    assert updated['session']['startup_urls']==['https://pve.example:8006']
    assert 'retain-private' not in json.dumps(result) and result['runtime_verified'] is False
    with (data/'RUN.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(er.RecipeError,match='stop application'):ab.apply_configuration(data,{'homepage':'https://another.example'})
    with pytest.raises(er.RecipeError):ab.apply_configuration(data,{'secret':'new-secret'})


def test_suite_rebuild_materializes_locked_apps_and_reattaches_private_data(tmp_path):
    import application_bundle as ab
    import tarfile,hashlib
    payload=tmp_path/'payload';payload.write_text('#!/bin/sh\nexit 0\n');payload.chmod(0o755)
    archive=tmp_path/'code.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:tar.add(payload,arcname='VSCode-linux-x64/code')
    sha=hashlib.sha256(archive.read_bytes()).hexdigest()
    source={'url':'https://vscode.download.prss.microsoft.com/dbazure/download/stable/'+('a'*40)+'/code-stable-x64-1.tar.gz','sha256':sha,'version':'1.0','package':'code','medium':'tar.gz'}
    recipe=ab.bind('vscode',{'editor.tabSize':2},source,ab.target_platform())
    suite=ab.compose([recipe]);cache=tmp_path/'cache';cache.mkdir();(cache/(sha+'.tar.gz')).write_bytes(archive.read_bytes())
    first=ab.build_suite(suite,cache,tmp_path/'generation1',tmp_path/'appdata')
    note=tmp_path/'appdata/vscode/home/note';note.write_text('personal content')
    second=ab.build_suite(suite,cache,tmp_path/'generation2',tmp_path/'appdata')
    assert first['applications']['vscode']['archive_verified'] is True
    inspected=ab.inspect_suite(suite,tmp_path/'generation1',tmp_path/'appdata')
    assert inspected['materialized'] is True and inspected['runtime_verified'] is False
    binary=Path(first['applications']['vscode']['executable']);original=binary.read_bytes();binary.write_bytes(b'changed')
    with pytest.raises(er.RecipeError,match='executable'):ab.inspect_suite(suite,tmp_path/'generation1',tmp_path/'appdata')
    binary.write_bytes(original)
    assert second['applications']['vscode']['retained_identity']==first['applications']['vscode']['retained_identity']
    assert second['runtime_verified'] is False and note.read_text()=='personal content'
    assert 'personal content' not in json.dumps(suite)
    with pytest.raises(er.RecipeError):ab.compose([recipe,recipe])
    with pytest.raises(er.RecipeError):ab.build_suite(suite,cache,tmp_path/'generation3',cache/'private')
    assert not (tmp_path/'generation3').exists()


def test_login_browser_grant_mounts_only_browser_code_and_scoped_uri_helper(tmp_path,monkeypatch):
    import application_bundle as ab
    generation=tmp_path/'application';generation.mkdir();data=tmp_path/'private';data.mkdir();(data/'home').mkdir()
    browser=tmp_path/'browser';browser.mkdir();(browser/'root').mkdir()
    source={'url':'https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_1.0_amd64.deb','sha256':'a'*64,'version':'1.0','package':'google-chrome-stable','medium':'deb'}
    recipe=ab.bind('chrome',{},source,ab.target_platform());(browser/'BUILD.json').write_text(ab.export(recipe))
    executable=browser/'root'/ab.EXECUTABLES['chrome'];executable.parent.mkdir(parents=True);executable.write_text('synthetic');executable.chmod(0o755)
    helper=tmp_path/'uri-helper';helper.write_text(ab.OPEN_URI_SCRIPT);helper.chmod(0o755)
    monkeypatch.setattr(ab,'URI_HELPER',str(helper));monkeypatch.setattr(ab,'_trusted_helper',lambda path:Path(path))
    (generation/'BUILD.json').write_text(ab.export(ab.bind('chatgpt',{}, {'url':'https://persistent.oaistatic.com/codex-app-prod/linux/deb/latest/chatgpt_amd64.deb','sha256':'a'*64,'version':'1.0','package':'chatgpt','medium':'deb'},ab.target_platform())))
    ordinary=ab.sandbox_command(generation,data,['/bin/true'],environment={})
    assert '/login-browser' not in ordinary
    granted=ab.sandbox_command(generation,data,['/bin/true'],environment={},login_browser=browser)
    assert ['--ro-bind',str(browser/'root'),'/login-browser']==granted[granted.index(str(browser/'root'))-1:granted.index(str(browser/'root'))+2]
    assert str(browser) not in granted
    assert ['--ro-bind',str(helper),'/usr/bin/xdg-open']==granted[granted.index(str(helper))-1:granted.index(str(helper))+2]
    with pytest.raises(er.RecipeError):ab.sandbox_command(generation,data,['/bin/true'],environment={},login_browser=data)


def test_web_uri_helper_refuses_files_and_keeps_login_browser_profile_inside_app(monkeypatch,tmp_path):
    import application_bundle as ab
    import subprocess,sys
    calls=[];monkeypatch.setattr(subprocess,'Popen',lambda argv,**kw:calls.append(argv))
    monkeypatch.setattr(Path,'is_file',lambda path:True);monkeypatch.setattr('os.access',lambda *args:True)
    monkeypatch.setattr(sys,'argv',['xdg-open','file:///etc/passwd'])
    with pytest.raises(SystemExit) as refused:exec(ab.OPEN_URI_SCRIPT,{'__name__':'__main__'})
    assert refused.value.code==1 and not calls
    monkeypatch.setattr(sys,'argv',['xdg-open','https://example.com/login?state=synthetic'])
    with pytest.raises(SystemExit) as sent:exec(ab.OPEN_URI_SCRIPT,{'__name__':'__main__'})
    assert sent.value.code==0 and calls
    assert '--user-data-dir=/home/baseline/.config/login-browser' in calls[0]
    assert '--no-sandbox' not in calls[0]


def test_native_uri_callback_is_scoped_to_requesting_app(monkeypatch):
    import application_bundle as ab
    import subprocess,sys
    calls=[];monkeypatch.setattr(subprocess,'Popen',lambda argv,**kw:calls.append(argv))
    monkeypatch.setattr(Path,'is_file',lambda path:True);monkeypatch.setattr('os.access',lambda *args:True)
    monkeypatch.setenv('BASELINE_SOURCE_APP','claude')
    monkeypatch.setattr(sys,'argv',['xdg-open','codex://synthetic-callback'])
    with pytest.raises(SystemExit) as refused:exec(ab.OPEN_URI_SCRIPT,{'__name__':'__main__'})
    assert refused.value.code==1 and not calls
    monkeypatch.setattr(sys,'argv',['xdg-open','claude://claude.ai/new?surface=chat&source=desktop_action'])
    with pytest.raises(SystemExit) as sent:exec(ab.OPEN_URI_SCRIPT,{'__name__':'__main__'})
    assert sent.value.code==0 and calls[0][0]=='/app/root/usr/lib/claude-desktop/claude-desktop'


def test_callback_registration_uses_private_home_and_preserves_other_mime_defaults(tmp_path):
    import application_bundle as ab
    data=tmp_path/'private';data.mkdir();(data/'home/.config').mkdir(parents=True)
    defaults=data/'home/.config/mimeapps.list';defaults.write_text('[Default Applications]\ntext/plain=keep.desktop;\n')
    ab.configure_uri_handler(data,'chatgpt')
    text=defaults.read_text()
    assert 'text/plain = keep.desktop;' in text and 'x-scheme-handler/codex = baseline-app-uri.desktop;' in text
    entry=(data/'home/.local/share/applications/baseline-app-uri.desktop').read_text()
    assert 'Exec=/usr/bin/xdg-open %u' in entry
    assert '/opt/' not in entry and str(tmp_path) not in entry


def test_reviewed_runtime_helper_update_is_atomic_and_keeps_old_open_inode(tmp_path,monkeypatch):
    import application_bundle as ab
    path=tmp_path/'helper';path.write_bytes(b'old');path.chmod(0o755)
    monkeypatch.setattr('os.geteuid',lambda:0)
    monkeypatch.setattr(ab,'_trusted_helper',lambda value:Path(value))
    with pytest.raises(er.RecipeError,match='update'):ab.install_helper(path,b'new')
    assert path.read_bytes()==b'old'
    with path.open('rb') as old:
        ab.install_helper(path,b'new',update=True)
        assert old.read()==b'old' and path.read_bytes()==b'new'
    assert path.stat().st_mode&0o777==0o755


def test_cli_compose_retarget_apply_and_capture_have_real_input_arguments(tmp_path):
    import application_bundle as ab
    import subprocess
    cli=Path(__file__).resolve().parents[2]/'baseline/bin/baseline-apps'
    source={'url':'https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_1.0_amd64.deb','sha256':'a'*64,'version':'1.0','package':'google-chrome-stable','medium':'deb'}
    recipe=ab.bind('chrome',{},source,ab.target_platform());recipes=tmp_path/'recipes.json';recipes.write_text(json.dumps([recipe]))
    result=subprocess.run(['python3',str(cli),'compose',str(recipes)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    suite=tmp_path/'suite.json';suite.write_text(result.stdout)
    retarget=subprocess.run(['python3',str(cli),'retarget',str(suite),'--os','debian','--release','13'],capture_output=True,text=True)
    assert retarget.returncode==0,retarget.stderr
    assert json.loads(retarget.stdout)['platform']['os']=='debian'
    plan=subprocess.run(['python3',str(cli),'build-suite','--help'],capture_output=True,text=True)
    assert 'input generation data' in plan.stdout


def test_desktop_launchers_quote_paths_and_do_not_grant_browser_by_default(tmp_path):
    import application_bundle as ab
    import shlex
    generation=tmp_path/'build with spaces';generation.mkdir()
    data=tmp_path/'private';data.mkdir()
    suite=ab.compose([ab.bind('chrome',{}, {'url':'https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_1.0_amd64.deb','sha256':'a'*64,'version':'1.0','package':'google-chrome-stable','medium':'deb'},ab.target_platform())])
    (generation/'SUITE.json').write_text(json.dumps(suite))
    (generation/'INSTALL.json').write_text(json.dumps({'suite_digest':suite['digest'],'applications':{'chrome':{}},'runtime_verified':False}))
    cli=tmp_path/'baseline-apps';cli.write_text('#!/bin/sh\n');cli.chmod(0o755)
    result=ab.desktop_launchers(generation,data,tmp_path/'desktop/applications',cli=cli)
    entry=Path(result['entries']['chrome']).read_text()
    assert 'Name=Baseline Chrome' in entry and 'Terminal=false' in entry
    line=next(v[5:] for v in entry.splitlines() if v.startswith('Exec='))
    assert shlex.split(line)==[str(cli),'launch',str(generation/'chrome'),str(data/'chrome')]
    assert '--login-browser' not in entry and 'runtime_verified' not in entry
    with pytest.raises(er.RecipeError):ab.desktop_launchers(generation,data,tmp_path/'desktop/applications',cli=cli)
    malformed=tmp_path/'bad';malformed.mkdir();(malformed/'SUITE.json').write_text(json.dumps(suite))
    (malformed/'INSTALL.json').write_text(json.dumps({'suite_digest':'wrong','applications':{'chrome':{}}}))
    with pytest.raises(er.RecipeError):ab.desktop_launchers(malformed,data,tmp_path/'bad-entries',cli=cli)
    assert not (tmp_path/'bad-entries').exists()


def test_runtime_install_keeps_package_output_out_of_machine_json(tmp_path,monkeypatch):
    import application_bundle as ab
    import subprocess,sys,shutil
    monkeypatch.setattr('os.geteuid',lambda:0)
    plan=ab.runtime_plan(ab.target_platform());plan['helper']=str(tmp_path/'bwrap');plan['uri_helper']=str(tmp_path/'uri')
    monkeypatch.setattr(ab,'runtime_plan',lambda platform:plan)
    monkeypatch.setattr(ab,'URI_HELPER',plan['uri_helper'])
    monkeypatch.setattr(ab,'install_helper',lambda path,payload,**kw:Path(path).write_bytes(payload))
    monkeypatch.setattr(shutil,'which',lambda value:None)
    monkeypatch.setattr(subprocess,'check_output',lambda *args,**kw:'bubblewrap=synthetic\n')
    calls=[]
    def run(argv,**kwargs):
        calls.append(argv)
        assert kwargs['stdout'] is sys.stderr
        return subprocess.CompletedProcess(argv,0)
    monkeypatch.setattr(subprocess,'run',run)
    result=ab.install_runtime()
    assert len(calls)==2 and result['runtime_verified'] is False


def test_storage_paths_refuse_parent_traversal_before_mutation(tmp_path):
    import application_bundle as ab
    with pytest.raises(er.RecipeError):ab._path(tmp_path/'cache/../private')
    assert not (tmp_path/'cache').exists() and not (tmp_path/'private').exists()
