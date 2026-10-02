"""Unit behavior with injected Proxmox runners; these are not boot proofs."""
import json
import tempfile
from pathlib import Path

import pytest

import distro_containers as dc


def test_catalog_offers_only_real_system_templates_from_the_host(tmp_path):
    def run(args):
        return 0, ("SECTION TEMPLATE\nsystem alpine-3.23-default_20260116_amd64.tar.xz\n"
                   "system debian-13-standard_13.1-2_amd64.tar.zst\n"
                   "turnkey turnkey-gitlab.tar.gz\nsystem ../../bad.tar.gz\n"), ""
    host = dc.DistroContainers(tmp_path, run=run)
    assert [t['name'] for t in host.catalog()] == [
        'alpine-3.23-default_20260116_amd64.tar.xz',
        'debian-13-standard_13.1-2_amd64.tar.zst']


class NativeRunner:
    def __init__(self):
        self.cache = tempfile.TemporaryDirectory(prefix='baseline-fake-source-')
        self.calls = []
        self.inputs = []
        self.nextid = 120
        self.states = {}
        self.configs = {}
        self.definitions = [
            {'storage': 'source-cache', 'type': 'dir', 'content': 'vztmpl', 'active': 1},
            {'storage': 'os-thin', 'type': 'lvmthin', 'content': 'rootdir', 'active': 1},
            {'storage': 'plain', 'type': 'dir', 'content': 'rootdir', 'active': 1}]

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ['pveam', 'download']:
            (Path(self.cache.name)/args[-1]).write_bytes(b'unit fixture, not a real distro')
        if args[:2] == ['pvesm', 'path']:
            return 0, str(Path(self.cache.name)/args[2].split('/')[-1]), ''
        if args[:2] == ['pveam', 'available']:
            return 0, 'system alpine-3.23-default_20260116_amd64.tar.xz\n', ''
        if args[0] == 'pvesh' and args[2].endswith('/storage'):
            return 0, json.dumps(self.definitions), ''
        if args[:3] == ['pvesh', 'get', '/cluster/nextid']:
            self.nextid += 1
            return 0, str(self.nextid), ''
        if args[:2] == ['pct', 'start']:
            self.states[args[2]] = 'running'
        if args[:2] in (['pct', 'stop'], ['pct', 'shutdown']):
            self.states[args[2]] = 'stopped'
        if args[:2] == ['pct', 'status']:
            return 0, 'status: ' + self.states.get(args[2], 'stopped'), ''
        if args[:2] == ['pct', 'clone']:
            self.configs[args[3]] = {'hostname': args[-1], 'unprivileged': '1',
                                      'rootfs': f'os-thin:vm-{args[3]}-disk-0,size=8G'}
        if args[:2] == ['pct', 'set'] and '--delete' not in args:
            self.configs[args[2]].update({args[i][2:]: args[i+1] for i in range(3, len(args), 2)})
        if args[:2] == ['pct', 'config']:
            return 0, '\n'.join(f'{k}: {v}' for k,v in self.configs[args[2]].items()), ''
        return 0, '', ''

    def input(self, args, data):
        self.inputs.append((args, data))
        return 0, '', ''


def test_create_is_a_native_linked_clone_with_retained_data_and_a_fresh_login(tmp_path):
    run = NativeRunner()
    h = dc.DistroContainers(tmp_path/'protected', run=run, run_input=run.input,
                           password_factory=lambda: b'fresh-disposable',
                           password_hasher=lambda _: '$6$salt$hash')
    made = h.create('alpine-work', template=h.catalog()[0]['name'],
                    cache_storage='source-cache', os_storage='os-thin')
    assert made['username'] == 'root' and made['password'] == 'fresh-disposable'
    assert h.list_containers()[0]['running']
    clones = [a for a in run.calls if a[:2] == ['pct', 'clone']]
    assert len(clones) == 1 and clones[0][clones[0].index('--full')+1] == '0'
    assert not any('fresh-disposable' in arg or '$6$' in arg for a in run.calls for arg in a)
    assert run.inputs[0][1] == b'root:$6$salt$hash\n'
    assert h.data_path('alpine-work', 'home').is_dir()
    assert h.data_path('alpine-work', 'root').is_dir()
    assert h.data_path('alpine-work', 'data').is_dir()
    records = list((tmp_path/'protected').rglob('*.json'))
    assert records and all('fresh-disposable' not in p.read_text() for p in records)


def test_rebuild_resets_only_the_stopped_os_clone_and_keeps_all_three_data_areas(tmp_path):
    run = NativeRunner()
    h = dc.DistroContainers(tmp_path/'protected', run=run, run_input=run.input,
                           password_factory=lambda: b'fresh', password_hasher=lambda _: '$6$salt$hash')
    h.create('work', template=h.catalog()[0]['name'], cache_storage='source-cache', os_storage='os-thin')
    vmid = h.status('work')['vmid']
    for kind in ('home', 'root', 'data'):
        (h.data_path('work', kind)/'saved').write_text('keep '+kind)
    with pytest.raises(dc.vh.VmError, match='shut down'):
        h.rebuild('work')
    h.shutdown('work')
    h.rebuild('work')
    assert h.status('work')['vmid'] == vmid and h.status('work')['running']
    for kind in ('home', 'root', 'data'):
        assert (h.data_path('work', kind)/'saved').read_text() == 'keep '+kind
    detach = next(i for i,a in enumerate(run.calls) if '--delete' in a)
    destroy = next(i for i,a in enumerate(run.calls) if a[:2] == ['pct', 'destroy'])
    assert detach < destroy


def test_plain_directory_storage_is_not_offered_or_used_as_an_overlay(tmp_path):
    run = NativeRunner()
    h = dc.DistroContainers(tmp_path/'protected', run=run, run_input=run.input)
    assert h.storages()['overlay'] == ['os-thin']
    with pytest.raises(dc.vh.VmError, match='linked-clone'):
        h.create('work', template=h.catalog()[0]['name'], cache_storage='source-cache', os_storage='plain')
    assert not any(a[0] == 'pct' for a in run.calls)


def test_changed_or_additional_mounts_refuse_rebuild_without_touching_any_volume(tmp_path):
    run = NativeRunner()
    h = dc.DistroContainers(tmp_path/'protected', run=run, run_input=run.input,
                           password_factory=lambda: b'fresh', password_hasher=lambda _: '$6$salt$hash')
    h.create('work', template=h.catalog()[0]['name'], cache_storage='source-cache', os_storage='os-thin')
    h.shutdown('work')
    run.configs[str(h.status('work')['vmid'])]['mp3'] = 'somewhere:important,mp=/important'
    before = len(run.calls)
    with pytest.raises(dc.vh.VmError, match='additional'):
        h.rebuild('work')
    assert not any(a[:2] in (['pct','destroy'], ['pct','set']) for a in run.calls[before:])


def test_downloader_exit_zero_with_no_template_file_is_a_failure(tmp_path):
    native = NativeRunner()
    def run(args):
        if args[:2] == ['pveam', 'download']:
            return 0, 'download failed: DNS failure', ''
        return native(args)
    h = dc.DistroContainers(tmp_path/'protected', run=run, run_input=native.input,
                           password_factory=lambda: b'fresh', password_hasher=lambda _: '$6$salt$hash')
    with pytest.raises(dc.vh.VmError, match='template file'):
        h.create('work',template=h.catalog()[0]['name'],cache_storage='source-cache',os_storage='os-thin')
    assert not any(a[0]=='pct' for a in native.calls)


@pytest.mark.parametrize('bad', ['/etc/containers', '/mnt/BASELINE/personal', '/tmp/data,mp=/etc'])
def test_protected_data_cannot_target_system_disposable_or_option_injection_paths(tmp_path,bad):
    native=NativeRunner()
    h=dc.DistroContainers(bad,run=native,run_input=native.input)
    with pytest.raises(dc.vh.VmError):
        h.create('work',template='alpine-3.23-default_20260116_amd64.tar.xz',cache_storage='source-cache',os_storage='os-thin')
    assert not native.calls


def test_vanilla_template_download_cannot_land_in_retained_data(tmp_path):
    native=NativeRunner()
    store=tmp_path/'protected'
    def run(args):
        if args[:2]==['pvesm','path']:
            return 0,str(store/'public-template.tar.xz'),''
        return native(args)
    h=dc.DistroContainers(store,run=run,run_input=native.input)
    with pytest.raises(dc.vh.VmError,match='cache'):
        h.create('work',template=h.catalog()[0]['name'],cache_storage='source-cache',os_storage='os-thin')
    assert not any(a[:2]==['pveam','download'] for a in native.calls)


def test_exit_zero_start_without_a_running_container_is_not_reported_as_success(tmp_path):
    native=NativeRunner()
    def run(args):
        if args[:2]==['pct','start']:
            return 0,'',''
        return native(args)
    h=dc.DistroContainers(tmp_path/'protected',run=run,run_input=native.input,
                         password_factory=lambda:b'fresh',password_hasher=lambda _:'$6$salt$hash')
    with pytest.raises(dc.vh.VmError,match='running'):
        h.create('work',template=h.catalog()[0]['name'],cache_storage='source-cache',os_storage='os-thin')


def test_external_media_mount_paths_are_valid_but_runtime_state_is_not():
    dc.DistroContainers('/run/media/example/external/protected')._check_data()
    with pytest.raises(dc.vh.VmError, match='system paths'):
        dc.DistroContainers('/run/user/1000/protected')._check_data()


def test_known_failed_openeuler_template_refuses_before_allocating(tmp_path):
    native = NativeRunner()
    h = dc.DistroContainers(tmp_path/'protected', run=native, run_input=native.input)
    with pytest.raises(dc.vh.VmError, match='failed.*Proxmox'):
        h.prepare('openeuler-25.03-default_20250507_amd64.tar.xz', 'source-cache', 'os-thin')
    assert not native.calls
