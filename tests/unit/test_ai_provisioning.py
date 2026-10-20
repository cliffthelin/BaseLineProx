"""AI provisioning uses synthetic credentials and real encrypted temporary files."""
import json
import pytest


def test_custom_profile_is_sealed_and_materializes_only_in_runtime(tmp_path):
    import ai_provisioning as ai
    import vault
    v = vault.Vault(tmp_path / 'vault')
    v.set_passphrase('synthetic passphrase only')
    profile = {'providers': {'openai': {'env': {'OPENAI_API_KEY': 'synthetic-api-key'}, 'files': {}}}, 'mcp': {}}
    ai.save_profile(v, 'AI_SETUP_DEFAULT', profile, 'synthetic passphrase only')
    assert b'synthetic-api-key' not in (tmp_path / 'vault/AI_SETUP_DEFAULT').read_bytes()
    with pytest.raises(vault.VaultLocked):
        ai.load_profile(v, 'AI_SETUP_DEFAULT')
    loaded = ai.load_profile(v, 'AI_SETUP_DEFAULT', 'synthetic passphrase only')
    ai.materialize(loaded, tmp_path / 'runtime')
    assert 'synthetic-api-key' in (tmp_path / 'runtime/environment.json').read_text()
    assert (tmp_path / 'runtime/environment.json').stat().st_mode & 0o077 == 0


def test_installer_choice_defaults_off_and_has_no_inline_credentials():
    import ai_provisioning as ai
    assert ai.choice({})['mode'] == 'none'
    plan = {'host_configuration': {'ai_setup': {'mode': 'parent', 'providers': ['codex'], 'targets': ['substrate', 'baseline', 'vm:*', 'ct:*', 'kasm:*'], 'profile': 'AI_SETUP_DEFAULT'}}}
    assert ai.choice(plan)['providers'] == ['codex']
    plan['host_configuration']['ai_setup']['api_key'] = 'synthetic secret'
    with pytest.raises(ai.SetupError):
        ai.choice(plan)


def test_parent_import_stays_opaque_and_child_gets_only_sealed_profile_and_grants(tmp_path):
    import ai_provisioning as ai
    import vault
    parent = tmp_path / 'home'
    p = parent / '.codex/auth.json'
    p.parent.mkdir(parents=True)
    p.write_text('{"synthetic":"credential-for-test"}')
    profile = ai.import_parent(parent, ['codex'], environ={})
    store = vault.Vault(tmp_path / 'parent-vault')
    store.set_passphrase('synthetic passphrase only')
    ai.save_profile(store, ai.PROFILE, profile, 'synthetic passphrase only')
    plan = {'host_configuration': {'ai_setup': {'mode': 'parent', 'providers': ['codex'], 'targets': ['baseline', 'vm:*'], 'profile': ai.PROFILE}}}
    admin = tmp_path / 'USER_ADMIN'
    admin.mkdir()
    result = ai.apply_plan(plan, admin, source_vault=store.root)
    assert result['state'] == 'prepared'
    assert b'credential-for-test' not in (admin / 'vault' / ai.PROFILE).read_bytes()
    assert json.loads((admin / 'ai-setup.json').read_text())['targets'] == ['baseline', 'vm:*']
    assert not (admin / '.codex').exists()
    assert ai.apply_plan({}, admin)['state'] == 'not requested'


def test_runtime_preserves_native_mcp_files_and_keys_never_enter_command_arguments(tmp_path):
    import ai_provisioning as ai
    import ai_runtime
    import base64
    profile = {'providers': {'codex': {'env': {'OPENAI_API_KEY': 'synthetic-api-key'}, 'files': {'.codex/config.toml': base64.b64encode(b'[mcp_servers.test]\ncommand="test-only"').decode()}}}, 'mcp': {}}
    argv, data = ai.delivery(profile, account='root')
    assert 'synthetic-api-key' not in ' '.join(argv)
    assert b'synthetic-api-key' in data
    env = ai_runtime.environment(profile, 'codex', tmp_path)
    assert env['OPENAI_API_KEY'] == 'synthetic-api-key'
    assert '[mcp_servers.test]' in (tmp_path / 'codex/home/.codex/config.toml').read_text()


def test_container_delivery_uses_managed_identity_and_stdin(monkeypatch, tmp_path):
    from distro_containers import DistroContainers
    host = DistroContainers(tmp_path)
    seen = []
    monkeypatch.setattr(host, '_managed', lambda name: {'vmid': 901})
    monkeypatch.setattr(host, 'status', lambda name: {'running': True})
    host.run_input = lambda argv, data: seen.append((argv, data)) or (0, '', '')
    host.guest_exec('synthetic', ['python3', '-c', 'pass'], b'synthetic-input')
    assert seen == [(['pct', 'exec', '901', '--', 'python3', '-c', 'pass'], b'synthetic-input')]


def test_http_custom_setup_saves_only_references_in_draft_and_can_activate_host(tmp_path):
    import vault
    import ai_provisioning as ai
    from configuration_drafts import DraftStore
    from test_baseline_web import _RealServerCase, _base_deps
    from test_install_plan import discover, proxmox_disk, baseline_disk
    root = tmp_path / 'vault'
    store = vault.Vault(root)
    store.set_passphrase('synthetic passphrase only')
    drafts = DraftStore(tmp_path / 'drafts.sqlite')
    case = _RealServerCase(_base_deps(draft_store=drafts,
        vault_roots=[('USER_ADMIN', 'admin', str(root))], vault_passphrase='synthetic passphrase only',
        ai_parent_home=tmp_path / 'parent', ai_parent_environ={},
        ai_runtime_root=tmp_path / 'runtime', ai_launcher_path=tmp_path / 'bin/ai-run',
        install_plan_discovery=lambda: discover(proxmox_disk(), baseline_disk())))
    try:
        selection = {'mode': 'custom', 'providers': ['openai'], 'targets': ['baseline'], 'profile': ai.PROFILE}
        profile = {'providers': {'openai': {'env': {'OPENAI_API_KEY': 'synthetic-api-key'}, 'files': {}}}, 'mcp': {}}
        status, result = case.post_json('/ai-setup/installer-profile', {'selection': selection, 'profile': profile, 'revision': 0})
        assert status == 200, result
        assert 'synthetic-api-key' not in json.dumps(result)
        assert 'synthetic-api-key' not in json.dumps(drafts.get('root', 'installer'))
        assert 'synthetic-api-key' not in (root / ai.PROFILE).read_text()
        import os, pwd
        status, result = case.post_json('/ai-setup/activate', {'target': 'baseline', 'account': pwd.getpwuid(os.getuid()).pw_name})
        assert status == 200, result
        assert (tmp_path / f'runtime/{os.getuid()}/profile.json').exists()
        status, _ = case.post_json('/ai-setup/activate', {'target': 'vm:ungranted', 'account': ''})
        assert status == 409
    finally:
        case.close()


def test_mcp_custom_documents_are_rendered_into_native_client_paths(tmp_path):
    import ai_provisioning as ai
    profile = {'providers': {'codex': {'env': {}, 'files': {}}}, 'mcp': {'codex': '[mcp_servers.synthetic]\nurl="https://example.invalid/mcp"'}}
    rendered = ai.with_mcp(profile)
    ai.materialize(rendered, tmp_path)
    assert 'mcp_servers.synthetic' in (tmp_path / 'home/.codex/config.toml').read_text()


def test_sync_honors_explicit_grants_and_reports_failed_targets():
    import ai_sync
    profile = {'providers': {'openai': {'env': {'OPENAI_API_KEY': 'synthetic'}, 'files': {}}}, 'mcp': {}}
    config = {'mode': 'custom', 'providers': ['openai'], 'targets': ['ct:*'], 'profile': 'AI_SETUP_DEFAULT'}
    seen = []
    def push(target, data):
        seen.append(target)
        raise OSError('synthetic unavailable')
    report = ai_sync.deliver(config, profile, ['vm:other', 'ct:synthetic'], push)
    assert seen == ['ct:synthetic']
    assert report['delivered'] == [] and 'ct:synthetic' in report['pending']
    assert 'synthetic unavailable' not in json.dumps(report)


def test_unsealed_vault_and_different_child_vault_are_refused(tmp_path):
    import ai_provisioning as ai
    import vault
    profile = {'providers': {}, 'mcp': {}}
    with pytest.raises(ai.SetupError, match='passphrase'):
        ai.save_profile(vault.Vault(tmp_path / 'plain'), ai.PROFILE, profile, None)
    source = vault.Vault(tmp_path / 'source')
    source.set_passphrase('synthetic source passphrase')
    ai.save_profile(source, ai.PROFILE, profile, 'synthetic source passphrase')
    admin = tmp_path / 'admin'
    child = vault.Vault(admin / 'vault')
    child.set_passphrase('synthetic different passphrase')
    plan = {'host_configuration': {'ai_setup': {'mode': 'custom', 'providers': ['codex'], 'targets': ['baseline'], 'profile': ai.PROFILE}}}
    with pytest.raises(ai.SetupError, match='different vault'):
        ai.apply_plan(plan, admin, source_vault=source.root)


def test_inline_ai_credentials_are_refused_by_draft_storage(tmp_path):
    from configuration_drafts import DraftStore, DraftError
    drafts = DraftStore(tmp_path / 'drafts.sqlite')
    with pytest.raises(DraftError):
        drafts.save('synthetic', 'installer', {'host_configuration': {'ai_setup': {'mode': 'custom', 'api_key': 'synthetic-credential'}}}, expected_revision=0)
    assert drafts.get('synthetic', 'installer') is None


def test_real_launcher_process_uses_private_runtime_and_passes_no_secret_arguments(tmp_path):
    import ai_runtime
    import os, pwd, subprocess, sys
    profile = {'providers': {'openai': {'env': {'OPENAI_API_KEY': 'synthetic-child-key'}, 'files': {}}}, 'mcp': {}}
    source = __import__('pathlib').Path(ai_runtime.__file__).read_text()
    source += '\nRUNTIME = ' + repr(str(tmp_path / 'runtime')) + '\n'
    launcher = tmp_path / 'bin/baseline-ai-run'
    ai_runtime.install(profile, account=pwd.getpwuid(os.getuid()).pw_name, runtime=tmp_path / 'runtime', launcher=launcher, source=source)
    code = "import os; assert os.environ['OPENAI_API_KEY']=='synthetic-child-key'; assert '/runtime/' in os.environ['HOME']; print('runtime credentials available')"
    result = subprocess.run([str(launcher), 'openai', '--', sys.executable, '-c', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'runtime credentials available'
