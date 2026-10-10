"""Immutable installer code/configuration bundles and source/dependency preflight.

A prepared bundle is not an installed system. Cached source bytes must match
publisher locks; detached signature verification is reported separately.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
from urllib.parse import urlparse
from configuration_drafts import _validate, DraftError

PAYLOAD_TREES=('baseline','boot','automation','packaging','docs','tests')
HOST_TOOLS=('qemu-system-x86_64','qemu-img','xorriso','gpgv','curl','lsblk','udevadm','blkid','pvs','lvs','vgchange','mount','umount','unshare','nsenter','chroot')


class InputError(ValueError):
    pass


def source_root(module_path, *, installed=Path('/opt/baseline-src')):
    local=Path(module_path).resolve().parents[2]
    for candidate in (local,Path(installed)):
        if (candidate/'boot/provision.sh').is_file():return candidate
    raise InputError('Installer source payload unavailable')


def _hash(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def required_artifacts(plan):
    required=['proxmox_iso','proxmox_auto_install_assistant','ubuntu_base']
    apps=plan.get('applications',{}).get('apps',[]) if isinstance(plan.get('applications',{}),dict) else []
    if isinstance(apps,list):required += ['app:'+name for name in apps if isinstance(name,str)]
    return required


def inspect(root, plan, settings, *, artifact_locks, which=shutil.which, source_errors=()):
    root=Path(root);errors=list(source_errors)
    for tree in PAYLOAD_TREES:
        if not (root/tree).is_dir() or (root/tree).is_symlink():errors.append('Missing payload tree: '+tree)
    try:provision=(root/'boot/provision.sh').read_text()
    except OSError:provision='';errors.append('Provisioning script unavailable')
    for relative in sorted(set(re.findall(r'\$SRC/([A-Za-z0-9_./-]+)',provision))):
        if '..' in Path(relative).parts or (root/relative).is_symlink() or not ((root/relative).is_file() or (root/relative).is_dir()):errors.append('Missing provisioning dependency: '+relative)
    packages=[]
    for line in provision.splitlines():
        if line.strip().startswith('apt-get install '):
            for word in shlex.split(line)[2:]:
                if not word.startswith('-') and word not in packages:packages.append(word)
    for section in ('drivers','diagnostics'):
        values=settings.get(section,{})
        if isinstance(values,dict):
            for key,value in values.items():
                if key.endswith('_package') and isinstance(value,str) and re.fullmatch(r'[a-z0-9][a-z0-9+.-]*',value) and value not in packages:packages.append(value)
    missing_tools=[name for name in HOST_TOOLS if not which(name)]
    errors += ['Missing installer host tool: '+name for name in missing_tools]
    artifacts=[]
    for name in required_artifacts(plan):
        lock=artifact_locks.get(name)
        row={'id':name,'verified':False,'signature_verified':False}
        if not isinstance(lock,dict):errors.append('Missing publisher source lock: '+name)
        else:
            raw_path=lock.get('path')
            if not isinstance(raw_path,str) or not raw_path:
                errors.append('Missing regular source path: '+name);artifacts.append(row);continue
            path=Path(raw_path);digest=lock.get('sha256','');url=lock.get('url','')
            row.update(path=str(path),url=url,expected_sha256=digest)
            if not isinstance(url,str) or urlparse(url).scheme!='https' or not urlparse(url).hostname:
                errors.append('Missing HTTPS publisher origin: '+name)
            elif not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest):
                errors.append('Missing SHA256 publisher lock: '+name)
            elif path.is_symlink() or not path.is_file():errors.append('Missing regular source file: '+name)
            elif _hash(path)!=digest:errors.append('Source digest mismatch: '+name)
            else:
                row.update(verified=True,bytes=path.stat().st_size,assurance='SHA256 matches publisher lock; detached signature not checked')
        artifacts.append(row)
    # Network-dependent target installation is explicit: host packages do not
    # prove that the target's package dependency closure has been acquired.
    errors.append('Target apt dependency closure, pinned NodeSource setup and Claude npm package are not bundled; prepare verified target packages before execution')
    return {'format':'baseline.installer-preflight/v1','ready':not errors,'sources_verified':bool(artifacts) and all(row['verified'] for row in artifacts),
            'publisher_signatures_verified':False,'required_artifacts':required_artifacts(plan),'artifacts':artifacts,
            'target_packages':packages,'missing_host_tools':missing_tools,'errors':errors,'executed':False}


def prepare(root,destination,*,plan,settings,recipe,artifact_locks,which=shutil.which,source_errors=()):
    root=Path(root);destination=Path(destination)
    for value in (plan,settings,recipe or {}):
        try:_validate(value)
        except DraftError as exc:raise InputError(str(exc)) from exc
    if destination.exists():raise InputError('Installer bundle destination already exists')
    report=inspect(root,plan,settings,artifact_locks=artifact_locks,which=which,source_errors=source_errors)
    missing=[error for error in report['errors'] if error.startswith(('Missing payload','Missing provisioning'))]
    if missing:raise InputError('; '.join(missing))
    destination.mkdir(parents=True,mode=0o700)
    incomplete=destination/'INCOMPLETE';incomplete.write_text('Bundle preparation has not completed\n')
    payload=destination/'payload';payload.mkdir()
    for tree in PAYLOAD_TREES:
        for item in (root/tree).rglob('*'):
            if item.is_symlink():raise InputError('Symlink in installer source payload: '+str(item.relative_to(root)))
        shutil.copytree(root/tree,payload/tree,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    config=destination/'configuration';config.mkdir(mode=0o700)
    values={'plan':plan,'settings':settings,'recipe':recipe}
    for name,value in values.items():
        with (config/(name+'.json')).open('x') as stream:
            json.dump(value,stream,sort_keys=True,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        os.chmod(config/(name+'.json'),0o600)
    report['prepared']=True
    files={str(path.relative_to(destination)):_hash(path) for path in sorted(destination.rglob('*')) if path.is_file() and path.name!='INCOMPLETE'}
    manifest={'format':'baseline.installer-input-bundle/v1','prepared':True,'preflight':report,'files':files}
    with (destination/'MANIFEST.json').open('x') as stream:
        json.dump(manifest,stream,sort_keys=True);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    incomplete.unlink()
    return report


def verify(destination):
    destination=Path(destination)
    if destination.is_symlink() or (destination/'INCOMPLETE').exists():raise InputError('Installer bundle incomplete')
    try:manifest=json.loads((destination/'MANIFEST.json').read_text())
    except (OSError,ValueError):raise InputError('Installer bundle manifest unavailable') from None
    if manifest.get('format')!='baseline.installer-input-bundle/v1' or not isinstance(manifest.get('files'),dict):raise InputError('Invalid installer bundle manifest')
    for relative,digest in manifest['files'].items():
        path=destination/relative
        if Path(relative).is_absolute() or '..' in Path(relative).parts or path.is_symlink() or not path.is_file() or _hash(path)!=digest:
            raise InputError('Installer bundle integrity check failed: '+relative)
    actual={str(path.relative_to(destination)) for path in destination.rglob('*') if path.is_file() and path.name!='MANIFEST.json'}
    if actual!=set(manifest['files']):raise InputError('Installer bundle integrity check failed: file set changed')
    report=manifest['preflight']
    for artifact in report.get('artifacts',[]):
        if not artifact.get('verified'):continue
        source=Path(artifact['path'])
        try:current=not source.is_symlink() and source.is_file() and _hash(source)==artifact['expected_sha256']
        except OSError:current=False
        if not current:
            artifact['verified']=False
            report['errors'].append('External source changed or unavailable: '+artifact['id'])
    report['sources_verified']=bool(report.get('artifacts')) and all(item.get('verified') for item in report['artifacts'])
    report['ready']=not report['errors']
    return report
