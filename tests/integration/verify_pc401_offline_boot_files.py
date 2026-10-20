"""Read-only real PC401 boot prerequisites; does not claim runtime boot.

Uses serial/size/PV/VG gates and debugfs without -w, mounts or journal replay.
Reads only named public boot/storage metadata; never private credentials.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'baseline/lib'))
import physical_device_safety as pds
import storage_policy


def run(argv):
    return subprocess.run(argv, check=True, capture_output=True, text=True, timeout=30).stdout


def verify():
    assert os.geteuid() == 0
    serial = 'SYNTHDRIVEB00002'
    disks = [d for d in json.loads(run(['lsblk', '-J', '-b', '-p', '-o', 'NAME,TYPE,SERIAL,SIZE']))['blockdevices'] if d.get('serial') == serial]
    assert len(disks) == 1
    target = pds.validate_target_device(disks[0]['name'], expected_serial=serial,
                                      min_size_bytes=512110190592, max_size_bytes=512110190592)
    pv = target['path'] + '3'
    identities = json.loads(run(['pvs', '--devices', pv, '--reportformat', 'json', '-o', 'pv_name,pv_uuid,vg_name,vg_uuid,pv_count']))['report'][0]['pv']
    assert len(identities) == 1
    identity = identities[0]
    assert identity['vg_name'] == 'baseline_1b75c1a556ee' and int(identity['pv_count']) == 1
    assert identity['pv_uuid'] == 'PtJxk3-3YnM-AnWA-fsJQ-MbDy-TJOB-yiCyM8'
    assert identity['vg_uuid'] == 'Okyyas-6SZq-tSzV-trFO-K5RW-hmXQ-TWPyAE'
    inventory = json.loads(run(['lvs', '--devices', pv, '--reportformat', 'json', '-o', 'lv_name,lv_path,vg_name']))['report'][0]['lv']
    assert all(lv['vg_name'] == identity['vg_name'] for lv in inventory)
    volumes = {lv['lv_name']: lv['lv_path'] for lv in inventory}
    root = volumes['root']

    def read(path, volume=root):
        assert re.fullmatch(r'/[A-Za-z0-9_.+/-]+', path) and '..' not in path.split('/')
        result = subprocess.run(['debugfs', '-R', 'cat ' + path, volume], capture_output=True, text=True, check=True, timeout=30)
        # debugfs can exit zero even when its requested command fails.
        errors = result.stderr.splitlines()
        assert len(errors) == 1 and errors[0].startswith('debugfs '), result.stderr
        assert result.stdout, f'No readable regular file at {path}'
        return result.stdout

    fstab = [line.split() for line in read('/etc/fstab').splitlines() if line and not line.startswith('#')]
    bindings = {line[1]: line[0] for line in fstab}
    assert len(bindings) == len(fstab), 'Duplicate fstab destinations'
    role_lvs = {'BASELINE': 'baseline_app_state', 'INSTALLER_CACHE': 'baseline_installer_cache',
                'SESSION_TEMP': 'baseline_session_temp', 'SUBSTRATE': 'baseline_substrate',
                'USER_ADMIN': 'baseline_user_admin', 'USER_PERSONAL': 'baseline_user_personal',
                'APPDATA_ADMIN': 'baseline_appdata_admin', 'APPDATA_PERSONAL': 'baseline_appdata_personal'}
    uuids = {}
    for role, lv in role_lvs.items():
        uuid = run(['blkid', '-s', 'UUID', '-o', 'value', volumes[lv]]).strip()
        assert bindings['/mnt/' + role] == 'UUID=' + uuid
        uuids[role] = uuid
    assert len(set(uuids.values())) == 8
    root_uuid = run(['blkid', '-s', 'UUID', '-o', 'value', root]).strip()
    assert bindings['/'] == 'UUID=' + root_uuid
    marker = json.loads(read('/etc/baseline/independent-drive.json'))
    assert marker['serial'] == serial and marker['root_uuid'] == root_uuid
    assert marker['vg_uuid'] == identity['vg_uuid'] and marker['pv_uuid'] == identity['pv_uuid']
    policy = json.loads(read("/storage-policy.json", volumes["baseline_substrate"]))
    storage_policy.validate_policy(policy)
    assert policy["serial"] == serial and policy["size_bytes"] == 512110190592
    assert {role: binding["uuid"] for role, binding in policy["bindings"].items()} == uuids
    assert marker['policy_path'] == storage_policy.POLICY_PATH
    grub = read('/boot/grub/grub.cfg')
    assert identity['vg_uuid'] in grub and root_uuid in grub
    assert 'root=/dev/mapper/baseline_1b75c1a556ee-root' in grub
    assert 'root=/dev/mapper/pve-root' not in grub
    boot_paths = sorted(set(re.findall(r'^\s*(?:linux|initrd)\s+(/boot/[^\s]+)', grub, re.M)))
    assert any('/vmlinuz-' in path for path in boot_paths) and any('/initrd.img-' in path for path in boot_paths)
    for path in boot_paths:
        metadata = run(['debugfs', '-R', 'stat ' + path, root])
        assert 'Type: regular' in metadata and re.search(r'Size:\s*[1-9][0-9]*', metadata), path
    services = {}
    for name in ('baseline-storage-verify.service', 'baseline-persist-bind-mounts.service'):
        text = read('/etc/systemd/system/' + name)
        assert 'ExecStart=' in text and 'RemainAfterExit=yes' in text
        stat = run(['debugfs', '-R', 'stat /etc/systemd/system/multi-user.target.wants/' + name, root])
        assert 'Type: symlink' in stat and name in stat, stat
        services[name] = hashlib.sha256(text.encode()).hexdigest()
    assert 'RequiresMountsFor=' in read('/etc/systemd/system/baseline-storage-verify.service')
    assert 'ID=debian' in read('/usr/lib/os-release')
    manifest = json.loads(read('/previous-layout-20261004/RESTORED.json', volumes['baseline_user_admin']))
    assert len(manifest) == 22 and all(re.fullmatch('[a-f0-9]{64}', item['sha256']) for item in manifest)
    print(json.dumps({'serial': serial, 'root_uuid': root_uuid, 'role_fstab_uuids_verified': uuids,
                      'marker_identity_verified': True, 'policy_present': bool(policy),
                      'renamed_grub_root_verified': True, 'boot_files_present': boot_paths,
                      'enabled_service_file_hashes': services, 'restoration_manifest_entries': len(manifest),
                      'scope': 'actual physical ext4/LVM read-only configuration; no mount, journal replay, runtime service or boot proof'}))


if __name__ == '__main__':
    verify()
