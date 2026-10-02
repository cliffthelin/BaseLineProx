"""Proxmox system distro containers. Native linked clones, not fake OverlayFS.

Template archives stay vanilla in selected cache storage. Clone-capable OS
storage holds the immutable template and disposable root. Retained bind data
is separate and is NOT covered by vzdump. Containers share the host kernel.
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import secrets
import socket
import subprocess
from pathlib import Path

import vm_host as vh
import drive_setup_answer as answer

DEFAULT_DATA = Path('/mnt/USER_ADMIN/ct-data')
ARCHIVE = re.compile(r'^[a-z0-9][a-z0-9_.+-]*_amd64\.tar\.(?:xz|gz|zst)$')
STORAGE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')


def _input(args, data):
    p = subprocess.run(args, input=data, capture_output=True, timeout=120)
    return p.returncode, p.stdout.decode(errors='replace'), p.stderr.decode(errors='replace')


class DistroContainers:
    def __init__(self, data_store=DEFAULT_DATA, *, run=vh._real_run, run_input=_input,
                 password_factory=answer.generate_one_time_password, password_hasher=None):
        self.data_store = Path(data_store)
        self.run = run
        self.run_input = run_input
        self.password_factory = password_factory
        self.password_hasher = password_hasher or (lambda p: answer.hash_password_sha512crypt(p, secrets.token_hex(8)))

    def command(self, args):
        rc, out, err = self.run(args)
        if rc:
            raise vh.VmError(f'{args[0]} {args[1]} failed: {err.strip()[-400:]}')
        return out

    def catalog(self):
        names = set()
        for line in self.command(['pveam', 'available', '--section', 'system']).splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] == 'system' and ARCHIVE.fullmatch(parts[1]):
                names.add(parts[1])
        return [{'name': name, 'family': name.split('-')[0]} for name in sorted(names)]

    def storages(self):
        node = socket.gethostname().split('.')[0]
        entries = json.loads(self.command(['pvesh', 'get', f'/nodes/{node}/storage', '--output-format', 'json']))
        active = [e for e in entries if e.get('active') and STORAGE.fullmatch(e.get('storage', ''))]
        return {
            'cache': [e['storage'] for e in active if 'vztmpl' in e.get('content', '').split(',')],
            'overlay': [e['storage'] for e in active if 'rootdir' in e.get('content', '').split(',')
                        and e.get('type') in ('lvmthin', 'zfspool')],
        }

    def _check_data(self):
        if not self.data_store.is_absolute() or self.data_store == Path('/'):
            raise vh.VmError('retained data needs its own absolute folder')
        if any(c in str(self.data_store) for c in ',\n\r') or '..' in self.data_store.parts:
            raise vh.VmError('retained path cannot contain mount options or traversal')
        forbidden = ('/dev', '/proc', '/sys', '/etc', '/boot', '/run/user', '/run/lock', '/usr', '/bin', '/sbin', '/lib', '/var/lib/dpkg')
        if any(str(self.data_store) == p or str(self.data_store).startswith(p+'/') for p in forbidden):
            raise vh.VmError('retained data must be outside system paths')
        if any(p.is_symlink() for p in (self.data_store, *self.data_store.parents)):
            raise vh.VmError('retained bind data paths cannot contain symlinks')
        vh.VmHost._check_store(self.data_store)
        if any(part in ('BASELINE', 'SUBSTRATE', 'SESSION_TEMP', 'INSTALLER_CACHE')
               for part in self.data_store.parts):
            raise vh.VmError('retained data cannot use a disposable or installer volume')

    def _record_path(self, name):
        vh.VmHost._need_name(name)
        return self.data_store / 'control' / 'containers' / f'{name}.json'

    def _save(self, path, value):
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        fresh = path.with_suffix('.new')
        fresh.write_text(json.dumps(value, indent=2))
        os.chmod(fresh, 0o600)
        os.replace(fresh, path)

    def record(self, name):
        try:
            return json.loads(self._record_path(name).read_text())
        except (OSError, ValueError):
            raise vh.VmError(f'no such Baseline container: {name}') from None

    def data_path(self, name, kind):
        vh.VmHost._need_name(name)
        if kind not in ('home', 'root', 'data'):
            raise vh.VmError('unknown retained data area')
        path = self.data_store / 'data' / name / kind
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise vh.VmError('retained data cannot use a symlinked path')
        return path

    def _nextid(self):
        vmid = int(self.command(['pvesh', 'get', '/cluster/nextid']).strip())
        if not 100 <= vmid <= 999999999:
            raise vh.VmError('Proxmox returned an invalid container ID')
        return vmid

    def prepare(self, template, cache_storage, os_storage, disk_gb=8):
        if template.startswith('openeuler-25.03-default_'):
            raise vh.VmError('this openEuler template failed setup on Proxmox 9.2.2; inspection and a verified fix are required')
        if template not in {t['name'] for t in self.catalog()}:
            raise vh.VmError('choose a current Proxmox system template')
        stores = self.storages()
        if cache_storage not in stores['cache'] or os_storage not in stores['overlay']:
            raise vh.VmError('choose active template cache and linked-clone-capable OS storage (LVM-thin or ZFS)')
        self._check_data()
        key = hashlib.sha256(f'{template}|{os_storage}|{disk_gb}'.encode()).hexdigest()[:20]
        path = self.data_store / 'control' / 'templates' / f'{key}.json'
        if path.exists():
            record = json.loads(path.read_text())
            if record.get('phase') != 'ready':
                raise vh.VmError('an incomplete template needs inspection in Proxmox; refusing replacement')
            return record
        archive = Path(self.command(['pvesm', 'path', f'{cache_storage}:vztmpl/{template}']).strip())
        resolved = archive.resolve()
        if (resolved.is_relative_to(self.data_store.resolve())
                or any(p in ('BASELINE', 'SUBSTRATE', 'SESSION_TEMP') or p.startswith(('USER_', 'APPDATA_'))
                       for p in resolved.parts)
                or any(p.is_symlink() for p in (archive, *archive.parents))):
            raise vh.VmError('vanilla cache must be separate from protected data and disposable OS storage')
        if resolved.is_relative_to('/mnt'):
            mount = Path('/mnt') / resolved.parts[2]
            if not os.path.ismount(mount):
                raise vh.VmError('installer cache volume is not mounted')
        self.command(['pveam', 'download', cache_storage, template])
        if not archive.is_file() or archive.is_symlink() or archive.stat().st_size == 0:
            raise vh.VmError('native download produced no template file; inspect Proxmox download/network status')
        vmid = self._nextid()
        record = {'vmid': vmid, 'template': template, 'os_storage': os_storage, 'phase': 'preparing'}
        self._save(path, record)
        self.command(['pct', 'create', str(vmid), f'{cache_storage}:vztmpl/{template}',
                      '--hostname', f'bl-base-{vmid}', '--rootfs', f'{os_storage}:{disk_gb}',
                      '--unprivileged', '1', '--memory', '512', '--cores', '1'])
        self.command(['pct', 'template', str(vmid)])
        record['phase'] = 'ready'
        self._save(path, record)
        return record

    def create(self, name, *, template, cache_storage, os_storage, disk_gb=8, memory_mb=512, cpus=1):
        vh.VmHost._need_name(name)
        if not (2 <= int(disk_gb) <= 128 and 128 <= int(memory_mb) <= 65536 and 1 <= int(cpus) <= 128):
            raise vh.VmError('container disk, memory or CPU size out of range')
        self._check_data()
        if self._record_path(name).exists() or self.data_path(name, 'home').parent.exists():
            raise vh.VmError('container name has existing retained state; refusing to replace it')
        base = self.prepare(template, cache_storage, os_storage, int(disk_gb))
        password = self.password_factory()
        record = {'name': name, 'vmid': self._nextid(), 'base_vmid': base['vmid'], 'template': template,
                  'os_storage': os_storage, 'memory_mb': int(memory_mb), 'cpus': int(cpus),
                  'password_hash': self.password_hasher(password), 'phase': 'creating'}
        self._save(self._record_path(name), record)
        for kind in ('home', 'root', 'data'):
            path = self.data_path(name, kind)
            path.mkdir(parents=True, mode=0o700)
            os.chmod(path, 0o700 if kind == 'root' else 0o755)
            # Default Proxmox unprivileged ID mapping. No custom idmap yet.
            self.command(['chown', '--no-dereference', '100000:100000', str(path)])
        self._clone(record)
        return {'name': name, 'username': 'root', 'password': password.decode('ascii'),
                'message': 'Container started. Save this one-time login. Home, root home and /data are retained.'}

    def _clone(self, record):
        vmid = str(record['vmid'])
        self.command(['pct', 'clone', str(record['base_vmid']), vmid, '--full', '0', '--hostname', record['name']])
        args = ['pct', 'set', vmid, '--memory', str(record['memory_mb']), '--cores', str(record['cpus']),
                '--net0', 'name=eth0,bridge=vmbr0,ip=dhcp', '--cmode', 'console']
        for idx, kind in enumerate(('home', 'root', 'data')):
            args += [f'--mp{idx}', f'{self.data_path(record["name"], kind)},mp=/{kind},backup=0']
        self.command(args)
        self.command(['pct', 'start', vmid])
        rc, _, _ = self.run_input(['pct', 'exec', vmid, '--', 'chpasswd', '-e'],
                                   f'root:{record["password_hash"]}\n'.encode())
        if rc:
            # Do not leave a running container with an unconfigured login.
            self.command(['pct', 'stop', vmid])
            raise vh.VmError('container password setup failed; machine stopped, retained state kept')
        if not self.status(record['name'])['running']:
            raise vh.VmError('container creation did not produce a running container; inspect incomplete state')
        record['phase'] = 'ready'
        self._save(self._record_path(record['name']), record)

    def status(self, name):
        record = self.record(name)
        state = self.command(['pct', 'status', str(record['vmid'])]).strip()
        if state not in ('status: running', 'status: stopped'):
            raise vh.VmError('unexpected container status')
        return {k: record[k] for k in ('name', 'vmid', 'base_vmid', 'template', 'os_storage', 'phase')} | {
            'running': state == 'status: running', 'data_path': str(self.data_path(name, 'home').parent)}

    def list_containers(self):
        d = self.data_store / 'control' / 'containers'
        return [self.status(p.stem) for p in sorted(d.glob('*.json'))] if d.is_dir() else []

    def _managed(self, name):
        self._check_data()
        record = self.record(name)
        config = dict(line.split(': ', 1) for line in
                      self.command(['pct', 'config', str(record['vmid'])]).splitlines() if ': ' in line)
        if config.get('hostname') != name or config.get('unprivileged') != '1':
            raise vh.VmError('container identity or unprivileged mapping changed; inspection required')
        for idx, kind in enumerate(('home', 'root', 'data')):
            expected = f'{self.data_path(name, kind)},mp=/{kind}'
            actual = config.get(f'mp{idx}', '')
            if not actual.startswith(expected + ',') or 'backup=0' not in actual:
                # Proxmox serializes the fields in its own order.
                items = actual.split(',')
                if not items or items[0] != str(self.data_path(name, kind)) or f'mp=/{kind}' not in items:
                    raise vh.VmError('retained mount configuration changed; inspection required')
            if not self.data_path(name, kind).is_dir() or self.data_path(name, kind).is_symlink():
                raise vh.VmError('retained data is absent or redirected; refusing operation')
        if any(re.fullmatch(r'(mp|unused)\d+', key) and key not in ('mp0', 'mp1', 'mp2') for key in config):
            raise vh.VmError('additional disks or mounts require an explicit recovery plan')
        if any(key.startswith('lxc.idmap') for key in config):
            raise vh.VmError('custom UID mapping is not supported by this retained-data recipe')
        root = config.get('rootfs', '').split(',')[0]
        allowed = {f'{record["os_storage"]}:{prefix}-{record["vmid"]}-disk-0' for prefix in ('vm', 'subvol')}
        if root not in allowed:
            raise vh.VmError('root volume ownership changed; refusing destructive operation')
        return record

    def shutdown(self, name):
        record = self._managed(name)
        self.command(['pct', 'shutdown', str(record['vmid']), '--timeout', '60'])
        if self.status(name)['running']:
            raise vh.VmError('container is still running; shutdown did not finish')

    def start(self, name):
        record = self._managed(name)
        if record.get('phase') != 'ready':
            raise vh.VmError('incomplete container needs recovery before starting')
        self.command(['pct', 'start', str(record['vmid'])])
        if not self.status(name)['running']:
            raise vh.VmError('container start did not produce a running container')

    def rebuild(self, name):
        record = self._managed(name)
        if self.status(name)['running']:
            raise vh.VmError('shut down cleanly before rebuilding the container OS')
        record['phase'] = 'rebuilding'
        self._save(self._record_path(name), record)
        self.command(['pct', 'set', str(record['vmid']), '--delete', 'mp0,mp1,mp2'])
        self.command(['pct', 'destroy', str(record['vmid']), '--purge', '1'])
        self._clone(record)
