"""Guarded offline update of an existing independent Proxmox installation.

No partitioning, formatting, credential injection or user-data restore. Only
the disposable BASELINE filesystem may grow, preserving a 16 GiB VG reserve. A web
action supplies a captured bundle; PolicyKit owns privileged authentication.
Completion means source/package deployment only, never boot acceptance.
"""
import argparse
import fcntl
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import drive_admin
import drive_guard
import drive_installer as di
import drive_recovery
import installer_inputs
import physical_device_safety as pds
import single_drive_storage as storage
import storage_policy


class UpdateError(RuntimeError):
    pass


from write_once import copy_changed        # the one way a tree is copied onto an existing build: only files that differ are written


BOOT_INPUTS = ('etc/initramfs-tools','etc/default/grub','etc/default/grub.d','etc/modules','etc/modules-load.d','etc/modprobe.d','etc/fstab','etc/crypttab','etc/kernel','etc/grub.d')


def boot_inputs_digest(root) -> str:
    """A digest of everything that decides what the boot images and the boot menu contain: their configuration, and which kernels and images exist (name and size, not content)."""
    import hashlib
    root = Path(root)
    digest = hashlib.sha256()
    for relative in BOOT_INPUTS:
        base = root / relative
        files = [base] if base.is_file() else sorted(p for p in base.rglob('*') if p.is_file()) if base.is_dir() else []
        for path in files:
            digest.update(str(path.relative_to(root)).encode() + b'\0' + hashlib.sha256(path.read_bytes()).digest())
    boot = root / 'boot'
    if boot.is_dir():
        for path in sorted(boot.iterdir()):
            if path.name.startswith(('vmlinuz-', 'initrd.img-', 'config-')) and path.is_file():
                digest.update(path.name.encode() + b'\0' + str(path.stat().st_size).encode())
    return digest.hexdigest()


def all_inactive(inventory) -> bool:
    """True when every logical volume of the group is inactive (a group that is not active reports every volume's use-state as unknown, not as free)."""
    return bool(inventory) and all(len(row.get('lv_attr','')) > 4 and row['lv_attr'][4] != 'a' for row in inventory)


def volumes_in_use(inventory) -> list:
    """The volumes that are open or whose use-state is unknown. A thin pool is held open by its own thin volumes once they are active: that is not a user, so only the volumes are checked."""
    return [row['lv_name'] for row in inventory if not row.get('lv_attr','').startswith('t') and row.get('lv_device_open') != '']


def baseline_growth_plan(current_bytes, vg_free_bytes, *, target_bytes=50*1024**3, reserve_bytes=16*1024**3):
    values=(current_bytes,vg_free_bytes,target_bytes,reserve_bytes)
    if any(type(value) is not int or value<0 for value in values) or not current_bytes or not target_bytes:
        raise UpdateError('Disposable capacity observation is invalid')
    growth=max(0,target_bytes-current_bytes)
    if growth and vg_free_bytes-growth<reserve_bytes:
        raise UpdateError('Disposable volume growth cannot preserve the VG reserve; retained volumes will not be shrunk')
    return {'grow_bytes':growth,'target_bytes':max(current_bytes,target_bytes),'remaining_vg_bytes':vg_free_bytes-growth}


def _require_update_serial(serial):
    if serial not in drive_admin.allowed_target_serials():
        raise UpdateError('Selected drive is not one of this installer lane\'s drives or enrolled; update refused')


def discover_path(serial, runner=None):
    from repair import RealRunner
    _require_update_serial(serial)
    import cardinality
    listing=storage._json_command(runner or RealRunner(),['lsblk','-J','-b','-p','-o','NAME,TYPE,SERIAL,SIZE,PTUUID'])
    disks=[d for d in listing.get('blockdevices',[]) if d.get('type')=='disk' and d.get('serial')==serial]
    try:
        cardinality.exactly_one(disks,'drive with the selected serial',describe=lambda d:str(d.get('name')))
    except cardinality.CardinalityError:
        raise UpdateError('Selected serial does not identify exactly one attached drive') from None
    if drive_guard.lane_verdict(disks[0].get('ptuuid'),serial)=='other' and serial not in drive_guard.own_drive_serials(released_only=True):
        raise UpdateError('Selected drive carries another installer lane\'s stamp; update refused')
    return pds.validate_target_device(disks[0]['name'],expected_serial=serial,
        min_size_bytes=disks[0]['size'],max_size_bytes=disks[0]['size'])['path']


def discover_recovery(serial, destination='/mnt/10TB/backup'):
    candidates=[]
    for folder in Path(destination).glob('baseline-recovery-*'):
        try:
            manifest=json.loads((folder/'MANIFEST.json').read_text())
            if (not folder.is_symlink() and manifest.get('serial')==serial
                    and manifest.get('complete') is True and manifest.get('source_compared') is True):
                candidates.append(folder)
        except (OSError,ValueError):
            continue
    if not candidates:
        raise UpdateError('No completed recovery snapshot found for the selected serial')
    return sorted(candidates,key=lambda path:path.name)[-1]


def inspect_update(bundle):
    bundle = Path(bundle)
    journal = bundle.parent / (bundle.name + '-update.json')
    if journal.is_symlink():
        raise UpdateError('Update journal is a symlink')
    state = json.loads(journal.read_text())
    if (state.get('format') != 'baseline.installed-drive-update/v1'
            or state.get('input_bundle') != str(bundle)
            or state.get('boot_verified') is not False
            or state.get('state') not in ('running','failed','updated','cleanup_failed')):
        raise UpdateError('Update journal identity or state is invalid')
    device = discover_path(state['serial'])
    return {'available':True, 'message':'Selected serial currently attached at '+device+
            '; deployment journal state='+state['state']+'. This is journal inspection only; '
            'boot, mounts, internet, firewall and workloads still require verification. '
            'Acknowledge before preparing a new reviewed update; no automatic replay.'}


def _target_path(root,relative):
    path=Path(root)
    for component in Path(relative).parts:
        if component in ('..','/'):
            raise UpdateError('Target path must remain inside the installed root')
        path=path/component
        if path.is_symlink():
            raise UpdateError('Target path contains a symlink requiring review: '+relative)
    return path


def _require_plain_tree(path):
    path = Path(path)
    if path.is_symlink() or (path.exists() and any(p.is_symlink() for p in path.rglob('*'))):
        raise UpdateError('Existing source tree contains a symlink requiring review')


def update(runner, *, serial, input_bundle, recovery_folder, root, pds_runner=None):
    _require_update_serial(serial)
    bundle = Path(input_bundle)
    installer_inputs.verify(bundle)  # Validate captured code before any device probe.
    import bluetooth_transfer
    plan = bluetooth_transfer.bundle_plan(bundle)
    bluetooth_transfer.requested(plan)  # reject malformed choices before hardware probes
    import ai_provisioning
    ai_provisioning.choice(plan)
    payload = bundle / 'payload'
    uid = runner.run(['id','-u'],timeout=10)
    if uid.returncode or uid.stdout.strip() != '0':
        raise UpdateError('Complete target-use inspection requires root')
    disk = drive_recovery._offline_disk(runner,serial)
    if drive_guard.lane_verdict(disk.get('ptuuid'),serial)=='other' and serial not in drive_guard.own_drive_serials(released_only=True):
        raise UpdateError('Selected drive carries another installer lane\'s stamp; update refused')
    target = pds.validate_target_device(disk['name'],expected_serial=serial,
        min_size_bytes=disk['size'],max_size_bytes=disk['size'],runner=pds_runner)
    partitions = [n['name'] for n in drive_recovery._walk([disk])
                  if n.get('type') == 'part' and n.get('fstype') == 'LVM2_member']
    if len(partitions) != 1:
        raise UpdateError('Recognized independent installation requires one physical PV')
    pv = partitions[0]
    records = storage._json_command(runner,['pvs','--devices',pv,'--reportformat','json',
        '-o','pv_name,pv_uuid,vg_name,vg_uuid,pv_count'])['report'][0]['pv']
    if (len(records) != 1 or records[0]['pv_name'] != pv
            or records[0].get('pv_count','').strip() != '1'):
        raise UpdateError('Physical PV/VG identity is ambiguous')
    identity = records[0]
    vg = identity['vg_name']
    if not re.fullmatch(r'[A-Za-z0-9_+.-]+',vg) or vg.startswith('-'):
        raise UpdateError('Invalid target VG identity')
    def read_inventory():
        return storage._json_command(runner,['lvs','--devices',pv,'--reportformat','json',
            '-o','lv_name,lv_attr,lv_device_open',vg])['report'][0]['lv']
    inventory = read_inventory()
    activated_here = False
    # A volume group that is not active reports every volume's use-state as unknown. When ALL of them are inactive nothing can be using them, so the group
    # is activated here (by its UUID: another drive may carry a group of the same name) and deactivated again when the update ends.
    if all_inactive(inventory):
        activation = runner.run(['vgchange','-ay','--select','vg_uuid='+identity['vg_uuid']],timeout=120)
        if activation.returncode:
            raise UpdateError('The target volume group could not be activated to update it')
        activated_here = True
        inventory = read_inventory()
    names = {row['lv_name'] for row in inventory}
    roles = di.baseline_volumes_for()
    if len(names) != len(inventory) or not {'root',*(v[0] for v in roles)}.issubset(names):
        raise UpdateError('Installed storage roles are incomplete; recovery/repair required')
    def deactivate():
        if activated_here:
            runner.run(['vgchange','-an','--select','vg_uuid='+identity['vg_uuid']],timeout=120)
    # a thin pool is held open by its own thin volumes once they are active: that is not a user of the volumes, so only the volumes themselves are checked
    if volumes_in_use(inventory):
        deactivate()
        raise UpdateError('Target volumes are open or use-state is unknown')
    for name in ('root',*(v[0] for v in roles)):
        used = runner.run(['fuser','--',f'/dev/{vg}/{name}'],timeout=15)
        if used.returncode != 1 or used.stdout.strip():
            deactivate()
            raise UpdateError('Target volume has users or process inspection failed')
    try:
        recovered = drive_recovery.verify_snapshot(runner,recovery_folder,expected_serial=serial)
        if recovered['size_bytes'] != target['size_bytes']:
            raise UpdateError('Recovery snapshot capacity differs from target')
        root = Path(root)
        if root.is_symlink() or not root.is_dir() or any(root.iterdir()):
            raise UpdateError('Private target mount directory must be empty and real')
    except Exception:
        deactivate()
        raise
    journal = bundle.parent / (bundle.name + '-update.json')
    state = {'format':'baseline.installed-drive-update/v1','serial':serial,
             'pv_uuid':identity['pv_uuid'],'vg_uuid':identity['vg_uuid'],
             'input_bundle':str(bundle),'state':'running','stages':[],
             'boot_verified':False,'updated_at':time.time()}
    def record(stage):
        state['stages'].append(stage);state['updated_at']=time.time()
        runner.write_text_atomic(str(journal),json.dumps(state,indent=2)+'\n')
        if journal.is_file() and not journal.is_symlink():
            os.chown(journal,bundle.stat().st_uid,bundle.stat().st_gid)
            os.chmod(journal,0o600)
    def guard():
        checked = pds.validate_target_device(target['path'],expected_serial=serial,
            min_size_bytes=target['size_bytes'],max_size_bytes=target['size_bytes'],runner=pds_runner)
        if checked != target:
            raise UpdateError('Selected physical identity changed')
        actual = storage._json_command(runner,['pvs','--devices',pv,'--reportformat','json',
            '-o','pv_name,pv_uuid,vg_name,vg_uuid,pv_count'])['report'][0]['pv']
        if actual != records:
            raise UpdateError('Selected PV/VG identity changed')
    def run(argv,timeout=60):
        guard()
        result = runner.run([str(v) for v in argv],timeout=timeout)
        if result.returncode:
            raise UpdateError('Update stage failed: '+str(argv[0]))
        return result
    mounted=[]
    service_policy=None
    service_policy_created=False
    user_admin_mount=None
    try:
        run(['mount','-o','ro,noload',f'/dev/{vg}/root',root]);mounted.append(root)
        observed = storage.inspect_target(runner,expected_serial=serial,root_mount=str(root))
        role_devices = {}
        for name,_,_,label,mountpoint in roles:
            device = f'/dev/{vg}/{name}'
            probe = run(['blkid','-o','export',device],timeout=15)
            facts = dict(line.split('=',1) for line in probe.stdout.splitlines() if '=' in line)
            if facts.get('TYPE') != 'ext4' or facts.get('LABEL') != label or not facts.get('UUID'):
                raise UpdateError('Storage role filesystem identity is missing: '+label)
            role_devices[label]=(device,facts['UUID'],mountpoint)
        marker_file = _target_path(root,'etc/baseline/independent-drive.json')
        if not marker_file.is_file():
            # /etc/baseline is kept on USER_ADMIN and bound over the root's own (empty) folder at boot: the identity marker is read from there, mounted read-only
            user_admin = _target_path(root,'mnt/USER_ADMIN')
            if not user_admin.is_dir() or user_admin.is_symlink():
                raise UpdateError('Installed USER_ADMIN mountpoint missing')
            run(['mount','-o','ro,noload',role_devices['USER_ADMIN'][0],user_admin]);mounted.append(user_admin);user_admin_mount=user_admin
            marker_file = user_admin/'etc-baseline'/'independent-drive.json'
        marker = json.loads(marker_file.read_text())
        if any(marker.get(k) != observed[k] for k in ('serial','root_uuid','pv_uuid','vg_uuid')):
            raise UpdateError('Installed root marker does not match physical identities')
        substrate = _target_path(root,'mnt/SUBSTRATE')
        if not substrate.is_dir() or substrate.is_symlink():
            raise UpdateError('Installed SUBSTRATE mountpoint missing')
        run(['mount','-o','ro,noload',role_devices['SUBSTRATE'][0],substrate]);mounted.append(substrate)
        policy = storage_policy.validate_policy(json.loads((substrate/'storage-policy.json').read_text()))
        if policy['serial'] != serial or policy['size_bytes'] != target['size_bytes']:
            raise UpdateError('Installed storage policy disagrees with target')
        for label,(_,identity_uuid,_) in role_devices.items():
            if policy['bindings'].get(label) != {'serial':serial,'uuid':identity_uuid}:
                raise UpdateError('Stored role routing differs from filesystem: '+label)
        # Validate fstab before the first writable mount. Never mount an arbitrary
        # stale LABEL or a filesystem belonging to the other independent drive.
        fstab = [line.split() for line in _target_path(root,'etc/fstab').read_text().splitlines()
                 if line.strip() and not line.lstrip().startswith('#')]
        for label,(_,identity_uuid,mountpoint) in role_devices.items():
            entries=[line for line in fstab if len(line)>3 and line[1]==mountpoint]
            if (len(entries)!=1 or entries[0][0]!='UUID='+identity_uuid
                    or entries[0][2]!='ext4'
                    or not (set(di.mount_options_for(label).split(',')) - {'defaults'}).issubset(set(entries[0][3].split(',')))):
                raise UpdateError('Installed role fstab routing is unsafe: '+label)
        run(['umount','--',substrate]);mounted.pop()
        if user_admin_mount is not None:                                  # mounted only to read the identity marker: it must be released before the root volume can be
            run(['umount','--',user_admin_mount]);mounted.remove(user_admin_mount)
        run(['umount','--',root]);mounted.pop()
        installer_inputs.verify(bundle)
        record('identity_source_recovery_and_retention_verified')
        from decimal import Decimal
        capacity=storage._json_command(runner,['lvs','--devices',pv,'--reportformat','json','--units','b','--nosuffix',
            '-o','lv_name,lv_size',vg])['report'][0]['lv']
        baseline_sizes=[int(Decimal(row['lv_size'].strip())) for row in capacity if row['lv_name']=='baseline_app_state']
        vg_capacity=storage._json_command(runner,['vgs','--devices',pv,'--reportformat','json','--units','b','--nosuffix',
            '-o','vg_name,vg_free',vg])['report'][0]['vg']
        if len(baseline_sizes)!=1 or len(vg_capacity)!=1 or vg_capacity[0]['vg_name']!=vg:
            raise UpdateError('Disposable volume or selected VG capacity is ambiguous')
        growth=baseline_growth_plan(baseline_sizes[0],int(Decimal(vg_capacity[0]['vg_free'].strip())))
        state['baseline_capacity']=growth
        if growth['grow_bytes']:
            device=role_devices['BASELINE'][0]
            guard();checked=runner.run(['e2fsck','-f','-p',str(device)],timeout=900)
            if checked.returncode not in (0,1):raise UpdateError('Disposable filesystem check failed; no volume growth attempted')
            run(['lvextend','--devices',pv,'--size',str(growth['target_bytes'])+'B','--',str(device)],timeout=300)
            record('disposable_volume_extended')
            run(['resize2fs',str(device)],timeout=900)
            record('disposable_filesystem_grown')
        run(['mount',f'/dev/{vg}/root',root]);mounted.append(root)
        for label,(device,_,mountpoint) in role_devices.items():
            dest=_target_path(root,mountpoint.lstrip('/'))
            if not dest.is_dir() or dest.is_symlink():
                raise UpdateError('Installed role mountpoint missing: '+label)
            run(['mount','-o',di.mount_options_for(label),device,dest]);mounted.append(dest)
        guard()
        state['bluetooth'] = bluetooth_transfer.apply_plan(plan, _target_path(root, 'mnt/USER_ADMIN'))
        state['ai_setup'] = ai_provisioning.apply_plan(plan, _target_path(root, 'mnt/USER_ADMIN'))
        record('parent_configuration_applied')
        for tree in installer_inputs.PAYLOAD_TREES:
            guard()
            destination = _target_path(root,'opt/baseline-src/'+tree)
            _require_plain_tree(destination)
            staged = copy_changed(payload/tree,destination,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))      # only files that differ are written
            state.setdefault('source_files',{})[tree] = staged
        record('captured_source_staged')
        # Keep the policy writer in the private target, never start target services
        # against the development host while provisioning an offline root.
        service_policy=_target_path(root,'usr/sbin/policy-rc.d')
        old_policy=service_policy.read_bytes() if service_policy.exists() else None
        if old_policy is not None:
            raise UpdateError('Existing service-start policy requires review')
        guard();service_policy.write_text('#!/bin/sh\nexit 101\n');service_policy.chmod(0o755)
        service_policy_created=True
        resolver=_target_path(root,'etc/resolv.conf')
        if resolver.is_symlink():
            raise UpdateError('Offline resolver symlink requires target-specific repair')
        import filecmp
        if not (resolver.is_file() and filecmp.cmp('/etc/resolv.conf',resolver,shallow=False)):      # written only when it differs
            guard();shutil.copy2('/etc/resolv.conf',resolver)
        for name,args in (('dev',['mount','--rbind','/dev']),('proc',['mount','-t','proc','proc']),
                          ('sys',['mount','--rbind','/sys'])):
            dest=_target_path(root,name)
            run(args+[str(dest)]);mounted.append(dest)
            if name in ('dev','sys'):run(['mount','--make-rslave',dest])
        installer_inputs.verify(bundle)
        boot_before = boot_inputs_digest(root)
        run(['chroot',root,'/usr/bin/env','BASELINE_OFFLINE_INSTALL=1',
             '/bin/bash','/opt/baseline-src/boot/provision.sh'],timeout=5400)
        record('current_baseline_provisioned')
        if boot_inputs_digest(root) != boot_before:                  # the boot images and menu are rebuilt only when something they are made from changed
            run(['chroot',root,'update-initramfs','-u','-k','all'],timeout=900)
            run(['chroot',root,'update-grub'],timeout=300)
            record('boot_files_refreshed')
        else:
            record('boot_files_unchanged')
        run(['sync'],timeout=300)
        state['state']='updated'
    except Exception:
        state['state']='failed'
        raise
    finally:
        if service_policy_created and service_policy.exists():
            guard();service_policy.unlink()
        cleanup_failed=[]
        for mountpoint in reversed(mounted):
            try:run(['umount','-R','--',mountpoint])
            except Exception:cleanup_failed.append(str(mountpoint))
        if cleanup_failed:
            state['state']='cleanup_failed'
        else:
            deactivate()                                       # the group is left as it was found
        record('cleanup_finished' if not cleanup_failed else 'cleanup_refused')
        if cleanup_failed:
            raise UpdateError('Ordinary unmount failed; target must not be booted: '+', '.join(cleanup_failed))
    return state


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial',required=True)
    parser.add_argument('--input-bundle',required=True)
    parser.add_argument('--recovery-folder',required=True)
    args=parser.parse_args()
    if os.geteuid()!=0:
        print('Installer update requires native privileged authorization',file=sys.stderr);return 1
    if os.environ.get('BASELINE_UPDATE_PRIVATE_MOUNT_NS')!='1':
        env=os.environ.copy();env['BASELINE_UPDATE_PRIVATE_MOUNT_NS']='1'
        os.execvpe('unshare',['unshare','--mount','--propagation','private',sys.executable,
            sys.argv[0],*sys.argv[1:]],env)
    try:
        _require_update_serial(args.serial)
        with open('/run/lock/baseline-drive-update-'+args.serial+'.lock','a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            from repair import RealRunner
            with tempfile.TemporaryDirectory(prefix='baseline-drive-update-') as root:
                result=update(RealRunner(),serial=args.serial,input_bundle=args.input_bundle,
                              recovery_folder=args.recovery_folder,root=root)
        print(json.dumps(result));return 0
    except Exception as exc:
        print('Installed-drive update refused: '+str(exc),file=sys.stderr);return 1
