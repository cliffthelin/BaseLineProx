"""Ubuntu environments: verified vanilla source, disposable root, retained /home.

The recipe provisions exactly one authenticated administrative account. It
never enables a guest login or accepts an operator's existing credentials.
Only the fresh user disk may be initialized. Rebuild seeds contain no mkfs.
Desktop installation requires network access on the first boot.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit

import drive_setup_answer as answer
import vm_host as vh

# Read from Canonical's HTTPS SHA256SUMS on 2026-10-01. The source is
# byte-pinned; publisher-signature verification is a later increment.
IMAGE_SHA256 = "6a81c37564db9b1ee84e141922625e1d7c5b389b99bb3c572e0243607d5bb4d2"
IMAGE_URL = ("https://cloud-images.ubuntu.com/releases/noble/release-20260926/"
             "ubuntu-24.04-server-cloudimg-amd64.img")
BASE_NAME = "ubuntu-noble-20260926"
USERNAME = "baseline-admin"


class UbuntuError(vh.VmError):
    pass


def _homepage(url: str) -> str:
    parsed = urlsplit(url)
    if (not re.fullmatch(r"https?://[A-Za-z0-9.:\[\]-]+/?", url)
            or not parsed.hostname or parsed.port != 8006 or parsed.path not in ("", "/")):
        raise UbuntuError("homepage must be a Proxmox http(s) endpoint on port 8006")
    return url


def configuration_overlay(*, desktop=True, homepage="https://baseline.invalid:8006", locale="en_US.UTF-8"):
    _homepage(homepage)
    if locale not in ('en_US.UTF-8','en_GB.UTF-8','C.UTF-8'):
        raise UbuntuError('unsupported Ubuntu locale')
    if not isinstance(desktop,bool):
        raise UbuntuError('desktop selection must be boolean')
    return {'format':'baseline.ubuntu-configuration/v1','desktop':desktop,
            'locale':locale,'homepage':homepage}


def browser_policy(homepage):
    return {"policies": {"Homepage": {"URL": homepage, "StartPage": "homepage"},
                         "DontCheckDefaultBrowser": True,
                         "OverrideFirstRunPage": homepage,
                         "OverridePostUpdatePage": ""}}


def cloud_config(*, password_hash: str, desktop: bool = True, locale: str = "en_US.UTF-8",
                 homepage: str = "https://baseline.invalid:8006", initialize_home: bool = False) -> str:
    overlay=configuration_overlay(desktop=desktop,homepage=homepage,locale=locale)
    if not password_hash.startswith("$6$") or any(c in password_hash for c in "\n\r"):
        raise UbuntuError("a salted password hash is required, never a plaintext credential")
    initialize = """
    if blkid -p "$disk" >/dev/null 2>&1; then
        echo 'Refusing to format an existing or unrecognized home filesystem' >&2; exit 1
    fi
    cmp -n 1048576 "$disk" /dev/zero || { echo 'Home disk is not blank' >&2; exit 1; }
    mkfs.ext4 -q -L baseline-home "$disk"
""" if initialize_home else """
    echo 'Retained home filesystem missing or damaged; recovery required' >&2; exit 1
"""
    prepare_home = """set -eu
disk=/dev/disk/by-id/virtio-baseline-home
[ -b "$disk" ] || { echo 'Retained home disk is absent' >&2; exit 1; }
if [ "$(blkid -s TYPE -o value "$disk" || true)" != ext4 ] ||
   [ "$(blkid -s LABEL -o value "$disk" || true)" != baseline-home ]; then
""" + initialize + """
fi
mkdir -p /home
if ! mountpoint -q /home; then mount -t ext4 "$disk" /home; fi
actual=$(findmnt -n -o SOURCE --mountpoint /home)
[ "$(readlink -f "$actual")" = "$(readlink -f "$disk")" ] ||
    { echo 'Wrong filesystem mounted at /home' >&2; exit 1; }
touch /run/baseline-home-ready
"""
    config = {
        "locale": locale,
        "disable_root": True,
        "ssh_pwauth": False,
        "users": [{"name": USERNAME, "uid": 1000, "groups": ["sudo"],
                   "shell": "/bin/bash", "lock_passwd": False, "hashed_passwd": password_hash,
                   "sudo": ["ALL=(ALL) ALL"]}],
        "package_update": True,
        "packages": ["qemu-guest-agent"] + (["ubuntu-desktop-minimal", "firefox"] if desktop else []),
        "bootcmd": [["bash", "-c", prepare_home]],
        "mounts": [["LABEL=baseline-home", "/home", "ext4", "defaults", "0", "2"]],
        "write_files": [{"path":"/etc/baseline/environment-configuration.json",
                         "permissions":"0644","content":json.dumps(overlay,sort_keys=True)+'\n'}],
        "runcmd": [["systemctl", "enable", "--now", "qemu-guest-agent"]],
    }
    if desktop:
        config["write_files"].append({
            "path":"/etc/xdg/autostart/baseline-browser.desktop","permissions":"0644",
            "content":f"[Desktop Entry]\nType=Application\nName=Environment browser\nExec=firefox --new-window {homepage}\nTryExec=firefox\nX-GNOME-Autostart-enabled=true\n",
        })
        config["write_files"].append({
            "path": "/etc/systemd/system/gdm3.service.d/baseline-home.conf", "permissions": "0644",
            "content": "[Unit]\nRequiresMountsFor=/home\nConditionPathExists=/run/baseline-home-ready\n",
        })
        config["write_files"].append({
            "path": "/etc/firefox/policies/policies.json", "permissions": "0644",
            "content": json.dumps(browser_policy(homepage)),
        })
        config["runcmd"].extend([
            ["mkdir", "-p", "/etc/firefox"],
            # Ubuntu Firefox is a snap and reads the policy here, rather
            # than at the deb Firefox path used above.
            ["cp", "/etc/firefox/policies/policies.json", "/etc/firefox/policies.json"],
            ["systemctl", "set-default", "graphical.target"],
            ["systemctl", "start", "gdm3"],
        ])
    checks = ("test -e /run/baseline-home-ready; "
              "findmnt --mountpoint /home >/dev/null; "
              "systemctl is-active --quiet qemu-guest-agent; ")
    if desktop:
        checks += "systemctl is-active --quiet gdm3; snap list firefox >/dev/null; "
    checks += "touch /var/lib/baseline-environment-ready"
    config["runcmd"].append(["bash", "-ec", checks])
    # JSON is a YAML subset. No quoting ambiguity around password hashes
    # or shell snippets; cloud-init reads this as ordinary cloud-config.
    return "#cloud-config\n" + json.dumps(config, indent=2) + "\n"


def _run(host, argv):
    rc, out, err = host.run(argv)
    if rc:
        raise UbuntuError(f"{argv[0]} failed: {err.strip()[-400:]}")
    return out


def verify_base(host,target,*,expected_source_sha256=IMAGE_SHA256):
    vh.VmHost._check_store(host.store)
    target=Path(target);receipt_path=target.with_suffix('.verification.json')
    if target.is_symlink() or not target.is_file():raise UbuntuError('Ubuntu base must be a regular image')
    if receipt_path.is_symlink():raise UbuntuError('Ubuntu base verification receipt must not be a symlink')
    try:receipt=json.loads(receipt_path.read_text())
    except (OSError,ValueError):raise UbuntuError('Ubuntu base verification receipt unavailable; existing backing image was not overwritten') from None
    if not isinstance(receipt,dict) or receipt.get('format')!='baseline.ubuntu-base-verification/v1' or receipt.get('source_sha256')!=expected_source_sha256:
        raise UbuntuError('Ubuntu base verification receipt does not match pinned source')
    with target.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
    if actual!=receipt.get('base_sha256'):raise UbuntuError('Ubuntu base digest mismatch; backing image was not overwritten')
    return target


def install_base(host, *, source: Path, expected_sha256: str = IMAGE_SHA256,
                 name: str = BASE_NAME) -> Path:
    vh.VmHost._check_store(host.store)
    vh.VmHost._need_name(name)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise UbuntuError("invalid source digest")
    if not source.is_file() or source.is_symlink():
        raise UbuntuError("source must be a regular downloaded image")
    with source.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected_sha256:
        raise UbuntuError("Ubuntu source digest mismatch")
    target = host.base_path(name)
    if target.exists():
        raise UbuntuError(f"base {name} already exists; never overwrite a backing image")
    target.parent.mkdir(parents=True, exist_ok=True)
    fresh = target.with_suffix(".new")
    try:
        _run(host, ["qemu-img", "convert", "-f", "qcow2", "-O", "qcow2", str(source), str(fresh)])
        if not fresh.is_file():
            raise UbuntuError("qemu-img produced no base image")
        os.chmod(fresh, 0o444)
        os.replace(fresh, target)
        with target.open('rb') as stream:base_sha256=hashlib.file_digest(stream,'sha256').hexdigest()
        receipt={'format':'baseline.ubuntu-base-verification/v1','source_sha256':expected_sha256,
                 'base_sha256':base_sha256,'signature_verified':False}
        with target.with_suffix('.verification.json').open('x') as stream:
            json.dump(receipt,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
        os.chmod(target.with_suffix('.verification.json'),0o444)
    finally:
        fresh.unlink(missing_ok=True)
    return target


def acquire_base(host, *, cache_dir: Path) -> Path:
    """Download only the pinned vanilla image. Other OS sources remain
    selectable through the ordinary ISO/template path."""
    target = host.base_path(BASE_NAME)
    if target.exists() or target.is_symlink():
        return verify_base(host,target,expected_source_sha256=IMAGE_SHA256)
    import installer_sources
    from repair import RealRunner
    cache_dir=Path(cache_dir)
    root=cache_dir.parent if cache_dir.name in ('images','isos') else cache_dir
    try:lock=installer_sources.acquire_ubuntu(RealRunner(),root)
    except installer_sources.SourceError as exc:raise UbuntuError(str(exc)) from exc
    return install_base(host,source=Path(lock['path']),expected_sha256=IMAGE_SHA256)


def write_seed(host, name, profile, *, initialize_home: bool):
    d = host.vm_dir(name)
    seed = d / "seed"
    seed.mkdir(mode=0o700, exist_ok=True)
    userdata = cloud_config(password_hash=profile["password_hash"], desktop=profile["desktop"],
                            homepage=profile["homepage"], locale=profile.get("configuration_overlay",{}).get("locale","en_US.UTF-8"), initialize_home=initialize_home)
    for filename, content in (
        ("user-data", userdata),
        ("meta-data", json.dumps({"instance-id": profile["instance_id"], "local-hostname": name})),
    ):
        path = seed / filename
        path.write_text(content)
        os.chmod(path, 0o600)
    fresh = d / "seed.new.iso"
    try:
        _run(host, ["xorriso", "-as", "mkisofs", "-volid", "cidata", "-joliet", "-rock",
                    "-o", str(fresh), str(seed / "user-data"), str(seed / "meta-data")])
        if not fresh.is_file():
            raise UbuntuError("seed builder produced no ISO")
        os.chmod(fresh, 0o600)
        os.replace(fresh, d / "seed.iso")
    finally:
        fresh.unlink(missing_ok=True)


def create(host, name: str, *, base: str = BASE_NAME, desktop: bool = True,
           homepage: str = "https://baseline.invalid:8006", memory_mb: int = 4096,
           cpus: int = 2, disk_gb: int = 40, persistence_gb: int = 32, locale: str = "en_US.UTF-8",
           password_factory=answer.generate_one_time_password, password_hasher=None) -> dict:
    overlay=configuration_overlay(desktop=desktop,homepage=homepage,locale=locale)
    if not 8 <= int(disk_gb) <= 4096:
        raise UbuntuError("Ubuntu root disk must be at least 8 GB")
    password = password_factory()
    hashed = (password_hasher or (lambda p: answer.hash_password_sha512crypt(p, secrets.token_hex(8))))(password)
    spec = host.create_overlay(name, base=base, memory_mb=memory_mb, cpus=cpus, persistence_gb=persistence_gb)
    profile = {"recipe": "ubuntu-desktop" if desktop else "ubuntu-server", "base": base, "desktop": bool(desktop),
               "homepage": homepage, "password_hash": hashed, "instance_id": secrets.token_hex(16),
               "disk_gb": int(disk_gb), "configuration_overlay":overlay}
    # Retained metadata is separate from the home filesystem and contains
    # only the one-way hash, never the one-time cleartext value.
    profile_path = Path(spec["persistence_disk"]).parent / "profile.json"
    _save_profile(profile_path, profile)
    try:
        _run(host, ["qemu-img", "resize", str(host.disk_path(name)), f"{int(disk_gb)}G"])
        write_seed(host, name, profile, initialize_home=True)
        spec.update({"recipe": profile["recipe"], "seed": True, "disk_gb": int(disk_gb), "configuration_overlay":overlay})
        host._write_spec(name, spec)
        host.configure_uefi(name)
    except Exception:
        # Never silently destroy retained state to undo a failed setup.
        # The incomplete machine remains stopped and can be inspected.
        raise
    return {"name": name, "username": USERNAME, "password": password.decode("ascii"),
            "message": "Created. Save the one-time login, then start the environment."}


def rebuild(host, name: str) -> None:
    spec = host._need_stopped(name)
    data = Path(spec.get("persistence_disk", ""))
    profile_path = data.parent / "profile.json"
    if not data.is_file() or not profile_path.is_file():
        raise UbuntuError("retained data or its profile is missing; refusing rebuild")
    profile = json.loads(profile_path.read_text())
    if profile.get('login_rotation'):
        raise UbuntuError('unfinished login rotation; use Reset login before rebuilding the OS')
    # Build the safe seed before touching the OS overlay. The retained disk
    # can never be formatted by a rebuild, even if it becomes corrupt.
    write_seed(host, name, profile, initialize_home=False)
    host.rollback(name)
    _run(host, ["qemu-img", "resize", str(host.disk_path(name)), f'{profile["disk_gb"]}G'])
    host._write_spec(name, spec)



def _save_profile(path, profile):
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise UbuntuError('retained profile path is redirected')
    fresh = path.with_suffix('.new')
    with fresh.open('w') as stream:
        os.chmod(fresh, 0o600)
        stream.write(json.dumps(profile, indent=2))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(fresh, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def reset_login(host, name, *, password_factory=answer.generate_one_time_password, password_hasher=None):
    spec = host._spec(name)
    if spec.get('recipe') not in ('ubuntu-desktop','ubuntu-server') or not callable(getattr(host,'guest_exec',None)):
        raise UbuntuError('login recovery currently supports managed Ubuntu environments on Proxmox with a guest agent')
    data = Path(spec.get('persistence_disk',''))
    path = data.parent/'profile.json'
    if not data.is_file() or data.is_symlink() or not path.is_file() or path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise UbuntuError('retained home or profile is absent or redirected')
    profile = json.loads(path.read_text())
    if profile.get('recipe')!=spec['recipe']:
        raise UbuntuError('retained recipe identity changed')
    # Verify actual readiness, account and mounted home before generating any credential.
    check = ('test -f /var/lib/baseline-environment-ready && test -f /run/baseline-home-ready && '
             'test "$(id -u baseline-admin)" = 1000 && '
             'test "$(readlink -f "$(findmnt -n -o SOURCE --mountpoint /home)")" = '
             '"$(readlink -f /dev/disk/by-id/virtio-baseline-home)"')
    try:
        host.guest_exec(name,['/bin/sh','-ec',check])
    except vh.VmError as exc:
        raise UbuntuError('Ubuntu readiness or native identity was not confirmed: '+str(exc)) from None
    password = password_factory()
    hashed = (password_hasher or (lambda p: answer.hash_password_sha512crypt(p,secrets.token_hex(8))))(password)
    if not hashed.startswith('$6$') or any(c in hashed for c in '\n\r'):
        raise UbuntuError('a salted generated password hash is required')
    # A crash after applying the hash must not let rebuild silently use the old credential.
    profile['login_rotation'] = {'phase':'applying','password_hash':hashed}
    _save_profile(path,profile)
    try:
        host.guest_exec(name,['chpasswd','-e'],f'{USERNAME}:{hashed}\n'.encode())
    except (vh.VmError,OSError,ValueError):
        raise UbuntuError('login rotation did not finish; journal kept. Retry Reset login before any OS rebuild.') from None
    profile['password_hash'] = hashed
    profile.pop('login_rotation')
    _save_profile(path,profile)
    return {'ok':True,'name':name,'username':USERNAME,'password':password.decode('ascii'),
            'message':'Fresh one-time Ubuntu login. OS and retained home were kept; future rebuilds use this login.'}


_CONFIGURATION_PROBE = r'''
import json, pathlib, shlex, subprocess

def command(argv):
    result=subprocess.run(argv,capture_output=True,text=True,timeout=8)
    return {'ok':result.returncode==0,'stdout':result.stdout.strip()}

def read_json(path):
    return json.loads(pathlib.Path(path).read_text())

configuration=read_json('/etc/baseline/environment-configuration.json')
locale={}
for line in pathlib.Path('/etc/default/locale').read_text().splitlines():
    if line.startswith('LANG='):
        locale['LANG']=shlex.split(line.split('=',1)[1])[0]
mount=command(['findmnt','-n','-o','SOURCE','--mountpoint','/home'])
expected=pathlib.Path('/dev/disk/by-id/virtio-baseline-home').resolve(strict=True)
actual=pathlib.Path(mount['stdout']).resolve(strict=True) if mount['ok'] else None
cloud=read_json('/var/lib/cloud/data/result.json')
report={'configuration':configuration,'locale':locale.get('LANG'),
        'home_bound':actual==expected,
        'cloud_init_done':isinstance(cloud.get('v1'),dict) and cloud['v1'].get('errors')==[],
        'ready_marker':pathlib.Path('/var/lib/baseline-environment-ready').is_file(),
        'agent_active':command(['systemctl','is-active','--quiet','qemu-guest-agent'])['ok']}
if configuration['desktop']:
    report.update(display_manager_active=command(['systemctl','is-active','--quiet','gdm3'])['ok'],
                  browser_available=command(['snap','list','firefox'])['ok'],
                  browser_policies=read_json('/etc/firefox/policies.json'))
print(json.dumps(report))
'''


def verify_configuration(host,name):
    """Observe configuration/services through a guarded native guest agent.

    This does not claim a logged-in desktop or browser page rendering.
    """
    if not callable(getattr(host,'guest_exec',None)):
        raise UbuntuError('Configuration verification requires the guarded native guest agent')
    spec=host._spec(name)
    if spec.get('recipe') not in ('ubuntu-desktop','ubuntu-server'):
        raise UbuntuError('Configuration verification requires a managed Ubuntu environment')
    profile_path=host.persistence_path(name).parent/'profile.json'
    if profile_path.is_symlink() or any(p.is_symlink() for p in profile_path.parents):
        raise UbuntuError('retained configuration profile is redirected')
    try:profile=json.loads(profile_path.read_text())
    except (OSError,ValueError):raise UbuntuError('retained configuration profile unavailable') from None
    selected=profile.get('configuration_overlay')
    if not isinstance(selected,dict):
        raise UbuntuError('This environment predates configuration overlays; create a new environment with an explicitly selected configuration')
    expected=configuration_overlay(desktop=profile['desktop'],homepage=profile['homepage'],locale=selected.get('locale'))
    if selected!=expected or profile['recipe']!=spec['recipe']:
        raise UbuntuError('retained configuration profile does not match the managed environment')
    try:
        native=host.guest_exec(name,['python3','-c',_CONFIGURATION_PROBE])
        if (not isinstance(native,dict) or native.get('exited') not in (True,1)
                or type(native.get('exitcode')) is not int or native['exitcode']!=0 or native.get('signal')):
            raise ValueError
        observed=json.loads(native.get('out-data',''))
        if not isinstance(observed,dict):raise ValueError
    except (vh.VmError,ValueError,TypeError):
        raise UbuntuError('Guest configuration observation unavailable; no success inferred') from None
    checks={'configuration':observed.get('configuration')==expected,
            'locale':observed.get('locale')==expected['locale']}
    checks.update({key:observed.get(key) is True for key in
                   ('home_bound','cloud_init_done','ready_marker','agent_active')})
    if expected['desktop']:
        checks.update({key:observed.get(key) is True for key in ('display_manager_active','browser_available')})
        checks['browser_policy']=observed.get('browser_policies')==browser_policy(expected['homepage'])
    passed=all(checks.values())
    return {'ok':passed,'name':name,'configuration_report':{'checks':checks,
            'configuration_applied':passed,'desktop_session_verified':False,'browser_page_loaded':False},
            'message':('Guest configuration and required services verified.' if passed else
                       'Guest checks failed: '+', '.join(key for key,value in checks.items() if not value))+
                      ' Logged-in desktop and browser page rendering still require GUI verification.'}
