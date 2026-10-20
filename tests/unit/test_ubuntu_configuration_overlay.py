import hashlib
import json
import pytest
import ubuntu_environment as ue
from test_vm_host import FakeHost


def test_selected_locale_and_browser_settings_are_materialized_in_cloud_init():
    config=json.loads(ue.cloud_config(password_hash='$6$test$hash',locale='en_GB.UTF-8',
        homepage='https://10.0.2.15:8006').split('\n',1)[1])
    assert config['locale']=='en_GB.UTF-8'
    overlay=next(item for item in config['write_files'] if item['path']=='/etc/baseline/environment-configuration.json')
    document=json.loads(overlay['content'])
    assert document['locale']=='en_GB.UTF-8'
    assert document['homepage']=='https://10.0.2.15:8006'
    assert document['desktop'] is True
    assert 'password' not in overlay['content']


def test_invalid_locale_is_refused_before_any_allocation(tmp_path):
    fake=FakeHost(tmp_path/'os')
    with pytest.raises(ue.UbuntuError,match='locale'):
        ue.create(fake.host,'desktop',locale='bad;command')
    assert not fake.run.calls
    assert not fake.host.vms_dir.exists()


def test_configuration_overlay_survives_os_rebuild_with_retained_home(tmp_path):
    fake=FakeHost(tmp_path/'os')
    fake.host.bases_dir.mkdir(parents=True)
    fake.host.base_path('ubuntu').write_bytes(b'test base')
    ue.create(fake.host,'desktop',base='ubuntu',locale='en_GB.UTF-8',
        password_factory=lambda:b'test-only',password_hasher=lambda p:'$6$test$hash')
    before=json.loads((fake.host.vm_dir('desktop')/'seed/user-data').read_text().split('\n',1)[1])
    fake.host.persistence_path('desktop').write_bytes(b'retained content')
    ue.rebuild(fake.host,'desktop')
    after=json.loads((fake.host.vm_dir('desktop')/'seed/user-data').read_text().split('\n',1)[1])
    assert before['locale']==after['locale']=='en_GB.UTF-8'
    assert fake.host.persistence_path('desktop').read_bytes()==b'retained content'
    assert 'mkfs' not in after['bootcmd'][0][2]
    profile=json.loads((fake.host.persistence_path('desktop').parent/'profile.json').read_text())
    assert profile['configuration_overlay']['locale']=='en_GB.UTF-8'


def test_missing_guest_observations_cannot_confirm_configuration(tmp_path):
    fake=FakeHost(tmp_path/'os')
    with pytest.raises(ue.UbuntuError,match='guest agent'):
        ue.verify_configuration(fake.host,'desktop')


def configured_host(tmp_path):
    fake=FakeHost(tmp_path/'os')
    fake.host.bases_dir.mkdir(parents=True)
    fake.host.base_path('ubuntu').write_bytes(b'test base')
    ue.create(fake.host,'desktop',base='ubuntu',locale='en_GB.UTF-8',
        password_factory=lambda:b'test-only',password_hasher=lambda p:'$6$test$hash')
    return fake.host


def guest_observation():
    return {'configuration':ue.configuration_overlay(locale='en_GB.UTF-8'),
        'locale':'en_GB.UTF-8','home_bound':True,'cloud_init_done':True,
        'ready_marker':True,'agent_active':True,'display_manager_active':True,
        'browser_available':True,'browser_policies':{'policies':{
            'Homepage':{'URL':'https://baseline.invalid:8006','StartPage':'homepage'},
            'DontCheckDefaultBrowser':True,'OverrideFirstRunPage':'https://baseline.invalid:8006',
            'OverridePostUpdatePage':''}}}


def test_guest_observations_verify_effective_configuration_without_claiming_gui(tmp_path):
    host=configured_host(tmp_path)
    host.guest_exec=lambda name,argv:{'exited':True,'exitcode':0,'out-data':json.dumps(guest_observation())}
    result=ue.verify_configuration(host,'desktop')
    assert result['ok']
    assert result['configuration_report']['configuration_applied']
    assert result['configuration_report']['browser_page_loaded'] is False
    assert result['configuration_report']['desktop_session_verified'] is False


@pytest.mark.parametrize('change',[
    lambda r:r.update(home_bound=False),lambda r:r.update(home_bound='true'),
    lambda r:r.pop('cloud_init_done'),lambda r:r.update(locale='en_US.UTF-8'),
    lambda r:r.update(browser_policies={}),lambda r:r.update(display_manager_active=False)])
def test_missing_or_mismatched_guest_checks_never_confirm_configuration(tmp_path,change):
    host=configured_host(tmp_path)
    observed=guest_observation();change(observed)
    host.guest_exec=lambda name,argv:{'exited':True,'exitcode':0,'out-data':json.dumps(observed)}
    assert not ue.verify_configuration(host,'desktop')['ok']


def test_guest_unobserved_exit_code_is_refused(tmp_path):
    host=configured_host(tmp_path)
    host.guest_exec=lambda name,argv:{'out-data':json.dumps(guest_observation())}
    with pytest.raises(ue.UbuntuError,match='observation unavailable'):
        ue.verify_configuration(host,'desktop')


def test_desktop_overlay_launches_configured_browser_after_authenticated_login():
    config=json.loads(ue.cloud_config(password_hash='$6$test$hash',desktop=True).split('\n',1)[1])
    startup=next(row for row in config['write_files'] if row['path']=='/etc/xdg/autostart/baseline-browser.desktop')
    assert 'Exec=firefox --new-window' in startup['content']
    assert 'TryExec=firefox' in startup['content']
    assert 'X-GNOME-Autostart-enabled=true' in startup['content']
    assert startup['permissions']=='0644'
    assert not any('autologin' in row['content'].lower() for row in config['write_files'])


def test_server_overlay_never_starts_a_gui_browser():
    config=json.loads(ue.cloud_config(password_hash='$6$test$hash',desktop=False).split('\n',1)[1])
    assert not any('/autostart/' in row['path'] for row in config['write_files'])


def test_first_browser_run_opens_configured_environment_homepage():
    import json
    from ubuntu_environment import cloud_config
    homepage = 'https://192.168.1.20:8006'
    cfg = json.loads(cloud_config(password_hash='$6$salt$hash', homepage=homepage).split('\n', 1)[1])
    policy = json.loads(next(f['content'] for f in cfg['write_files']
                            if f['path'] == '/etc/firefox/policies/policies.json'))['policies']
    assert policy['OverrideFirstRunPage'] == homepage
    assert policy['OverridePostUpdatePage'] == ''


def test_autostart_opens_homepage_even_with_a_retained_crash_session():
    import json
    from ubuntu_environment import cloud_config
    homepage = 'https://192.168.1.20:8006'
    cfg = json.loads(cloud_config(password_hash='$6$salt$hash', homepage=homepage).split('\n', 1)[1])
    desktop = next(f['content'] for f in cfg['write_files']
                   if f['path'] == '/etc/xdg/autostart/baseline-browser.desktop')
    assert f'Exec=firefox --new-window {homepage}\n' in desktop


def test_guest_verifier_accepts_the_policy_written_by_current_cloud_config(tmp_path):
    host = configured_host(tmp_path)
    config = json.loads(ue.cloud_config(password_hash='$6$test$hash').split('\n', 1)[1])
    observed = guest_observation()
    observed['browser_policies'] = json.loads(next(f['content'] for f in config['write_files']
                                                 if f['path'] == '/etc/firefox/policies/policies.json'))
    host.guest_exec = lambda name, argv: {'exited': True, 'exitcode': 0, 'out-data': json.dumps(observed)}
    assert ue.verify_configuration(host, 'desktop')['ok']
