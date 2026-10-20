import json
from pathlib import Path
import pytest
import installer_inputs as ii


def repository(root):
    for name in ii.PAYLOAD_TREES:
        (root/name).mkdir(parents=True)
    (root/'boot/provision.sh').write_text('apt-get install -y cage chromium\ncp "$SRC/baseline/lib/needed.py" /opt/baseline/lib/needed.py\nbash "$SRC/tests/console_font_check.sh"\n')
    (root/'baseline/lib').mkdir()
    (root/'baseline/lib/needed.py').write_text('VALUE = 1\n')
    (root/'tests/console_font_check.sh').write_text('true\n')
    return root


def test_missing_payload_dependency_is_reported_before_bundle_creation(tmp_path):
    root=repository(tmp_path/'repo')
    (root/'baseline/lib/needed.py').unlink()
    report=ii.inspect(root, {'applications':{'apps':['chrome']}}, {}, artifact_locks={}, which=lambda name:'/bin/'+name)
    assert not report['ready']
    assert any('needed.py' in error for error in report['errors'])
    assert 'cage' in report['target_packages']
    assert 'app:chrome' in report['required_artifacts']


def test_artifact_bytes_must_match_lock_and_raw_hash_is_not_publisher_signature(tmp_path):
    root=repository(tmp_path/'repo')
    source=tmp_path/'source.iso';source.write_bytes(b'changed')
    report=ii.inspect(root, {}, {}, artifact_locks={'proxmox_iso':{'path':str(source),'sha256':'0'*64,'url':'https://publisher.example/source.iso'}}, which=lambda name:'/bin/'+name)
    assert any('digest mismatch' in error for error in report['errors'])
    assert report['sources_verified'] is False


def test_bundle_contains_current_code_settings_and_recipe_and_detects_mutation(tmp_path):
    root=repository(tmp_path/'repo')
    bundle=ii.prepare(root,tmp_path/'bundle',plan={'environment':{'variant':'server'}},settings={'drivers':{'cpu_microcode':True}},recipe={'document':{'id':'draft'},'app_document':None},artifact_locks={},which=lambda name:'/bin/'+name)
    assert bundle['prepared'] and not bundle['ready'] and bundle['executed'] is False
    assert (tmp_path/'bundle/payload/tests/console_font_check.sh').is_file()
    assert json.loads((tmp_path/'bundle/configuration/settings.json').read_text())['drivers']['cpu_microcode'] is True
    assert ii.verify(tmp_path/'bundle')['prepared']
    (tmp_path/'bundle/payload/baseline/lib/needed.py').write_text('changed\n')
    with pytest.raises(ii.InputError,match='integrity'):
        ii.verify(tmp_path/'bundle')


def test_secret_configuration_cannot_be_bundled(tmp_path):
    root=repository(tmp_path/'repo')
    with pytest.raises(ii.InputError,match='Credentials'):
        ii.prepare(root,tmp_path/'bundle',plan={},settings={'password':'forbidden'},recipe=None,artifact_locks={})
    assert not (tmp_path/'bundle').exists()


def test_source_root_resolves_installed_payload_instead_of_opt(tmp_path):
    installed=repository(tmp_path/'baseline-src')
    assert ii.source_root(tmp_path/'baseline/lib/baseline_web.py', installed=installed)==installed


def test_malformed_source_path_is_reported_as_missing_lock(tmp_path):
    root=repository(tmp_path/'repo')
    report=ii.inspect(root, {}, {}, artifact_locks={'proxmox_iso':{'path':None,'sha256':'0'*64,'url':'https://publisher.example/source.iso'}},which=lambda name:'/bin/'+name)
    assert not report['ready']
    assert any('source path' in error for error in report['errors'])


def test_recursive_provisioning_directory_sources_are_valid(tmp_path):
    root=repository(tmp_path/'repo')
    (root/'boot/provision.sh').write_text('cp -a "$SRC/automation" /opt/baseline-src/automation\n')
    report=ii.inspect(root,{}, {},artifact_locks={},which=lambda name:'/bin/'+name)
    assert not any('Missing provisioning dependency' in error for error in report['errors'])


def test_bundle_report_rechecks_external_source_bytes(tmp_path):
    import hashlib
    root=repository(tmp_path/'repo')
    source=tmp_path/'source.iso';source.write_bytes(b'vanilla')
    lock={'path':str(source),'sha256':hashlib.sha256(b'vanilla').hexdigest(),'url':'https://publisher.example/source.iso'}
    folder=tmp_path/'bundle'
    ii.prepare(root,folder,plan={},settings={},recipe=None,artifact_locks={'proxmox_iso':lock},which=lambda name:'/bin/'+name)
    assert ii.verify(folder)['artifacts'][0]['verified']
    source.write_bytes(b'changed')
    assert ii.verify(folder)['artifacts'][0]['verified'] is False
