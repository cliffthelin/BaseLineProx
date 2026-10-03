"""Native application recipe workflow. Linux amd64 first; capabilities are explicit.

Portable exports exclude account/profile contents. Scale is a Baseline launch
setting, not a claim to capture all native application preferences.
"""
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
import environment_recipes as er
import vscode_capture as vc

APPS=('vscode','spotify','chrome','chatgpt','claude')


def _app(app):
    if app not in APPS:raise er.RecipeError('unsupported application')


def _homepage(value):
    if not isinstance(value,str) or len(value)>2048:raise er.RecipeError('invalid homepage')
    parsed=urlsplit(value)
    if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password or any(ord(c)<33 for c in value):
        raise er.RecipeError('homepage must be an HTTP(S) URL without credentials')
    return value


def capture(app,text):
    _app(app)
    if app=='vscode':
        captured=vc.capture(text)
        return {'app':app,'configuration':captured['document']['settings'],'excluded_count':captured['excluded_count']}
    doc=er.read_document(text)
    if not isinstance(doc,dict):raise er.RecipeError('configuration must be an object')
    approved={}
    for key,value in doc.items():
        if key=='scale':
            if type(value) not in (float,int) or not .75<=value<=2:raise er.RecipeError('unsupported display scale')
            approved[key]=value
        elif app=='chrome' and key=='homepage':approved[key]=_homepage(value)
    return {'app':app,'configuration':approved,'excluded_count':len(doc)-len(approved)}

PACKAGES={'chrome':'google-chrome-stable','spotify':'spotify-client','claude':'claude-desktop','chatgpt':'chatgpt','vscode':'code'}
SOURCES={
 'chrome':r'https://dl\.google\.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_[A-Za-z0-9.+~-]+_amd64\.deb',
 'spotify':r'https://repository\.spotify\.com/pool/non-free/s/spotify-client/spotify-client_[A-Za-z0-9.+~-]+_amd64\.deb',
 'claude':r'https://downloads\.claude\.ai/claude-desktop/apt/stable/pool/main/c/claude-desktop/claude-desktop_[A-Za-z0-9.+~-]+_amd64\.deb',
 'chatgpt':r'https://persistent\.oaistatic\.com/codex-app-prod/linux/deb/latest/chatgpt_amd64\.deb',
 'vscode':r'https://vscode\.download\.prss\.microsoft\.com/dbazure/download/stable/[0-9a-f]{40}/code-stable-x64-[0-9]+\.tar\.gz',
}


def bind(app,configuration,source,platform):
    _app(app)
    if (not isinstance(platform,dict) or set(platform)!={'os','release','arch'} or platform['arch']!='amd64'
            or (platform['os'],platform['release']) not in (('ubuntu','24.04'),('ubuntu','26.04'),('debian','13'))):
        raise er.RecipeError('unsupported target OS/release/architecture')
    checked=capture(app,json.dumps(configuration))
    if checked['excluded_count']:raise er.RecipeError('unapproved configuration in recipe')
    if (not isinstance(source,dict) or set(source)!={'url','sha256','version','package','medium'}
            or source.get('package')!=PACKAGES[app] or source.get('medium')!=('tar.gz' if app=='vscode' else 'deb')
            or not isinstance(source.get('url'),str) or not re.fullmatch(SOURCES[app],source['url'])
            or not isinstance(source.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',source['sha256'])
            or not isinstance(source.get('version'),str) or not re.fullmatch(r'[A-Za-z0-9.+:~_-]{1,128}',source['version'])):
        raise er.RecipeError('unsupported publisher source lock')
    return json.loads(json.dumps({'format':'baseline.application-build/v1','app':app,'platform':platform,
                                 'configuration':checked['configuration'],'source':source}))


def validate(recipe):
    if not isinstance(recipe,dict) or set(recipe)!={'format','app','platform','configuration','source'} or recipe['format']!='baseline.application-build/v1':
        raise er.RecipeError('unsupported application build envelope')
    return bind(recipe['app'],recipe['configuration'],recipe['source'],recipe['platform'])


def export(recipe):
    return json.dumps(validate(recipe),sort_keys=True,separators=(',',':'))+'\n'


def digest(recipe):
    return hashlib.sha256(export(recipe).encode()).hexdigest()

EXECUTABLES={'vscode':'VSCode-linux-x64/code','chrome':'opt/google/chrome/chrome',
             'spotify':'usr/share/spotify/spotify','claude':'usr/lib/claude-desktop/claude-desktop',
             'chatgpt':'usr/lib/chatgpt/ChatGPT'}


def _path(path):
    path=Path(path).absolute()
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):raise er.RecipeError('redirected path refused')
    return path


def _write(path,value):
    with path.open('x') as stream:
        os.chmod(path,0o600);json.dump(value,stream,sort_keys=True,indent=2)
        stream.flush();os.fsync(stream.fileno())


def target_platform():
    fields={}
    for line in Path('/etc/os-release').read_text().splitlines():
        if '=' in line:
            key,value=line.split('=',1);fields[key]=value.strip('"')
    arch={'x86_64':'amd64','aarch64':'arm64'}.get(os.uname().machine,os.uname().machine)
    return {'os':fields.get('ID','unknown'),'release':fields.get('VERSION_ID','unknown'),'arch':arch}


def _extract(archive,target,medium,prefix):
    import tarfile
    process=None
    if medium=='deb':
        process=subprocess.Popen(['dpkg-deb','--fsys-tarfile',str(archive)],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        context=tarfile.open(fileobj=process.stdout,mode='r|')
    else:context=tarfile.open(archive,mode='r:gz')
    size=0;seen=set()
    try:
        with context as tar:
            for member in tar:
                name=member.name.removeprefix('./').rstrip('/')
                if name in ('','.'):continue
                if not (name==prefix or name.startswith(prefix+'/')):continue
                if name in seen or not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                    raise er.RecipeError('unsupported archive entry')
                seen.add(name);size+=member.size
                if len(seen)>20000 or size>2*1024**3:raise er.RecipeError('archive extraction limit exceeded')
                if target is not None:tar.extract(member,target,filter='data')
        if process and process.wait(timeout=30):raise er.RecipeError('package extraction failed; partial target retained')
        return size
    except tarfile.FilterError as exc:raise er.RecipeError('unsafe archive path; partial target retained') from exc
    finally:
        if process:
            process.stdout.close()
            if process.poll() is None:process.terminate();process.wait(timeout=10)


PRIVATE_DBUS_CONFIG = '<busconfig>\n  <type>session</type>\n  <listen>unix:tmpdir=/tmp</listen>\n  <policy context="default">\n    <allow send_destination="*"/>\n    <allow receive_sender="*"/>\n    <allow own="*"/>\n  </policy>\n</busconfig>\n'


def install(recipe,archive,generation,data,*,platform=None):
    import uuid
    recipe=validate(recipe);archive=_path(archive);generation=_path(generation);data=_path(data)
    if recipe['platform']!=(platform or target_platform()):raise er.RecipeError('recipe target platform does not match this installation')
    if generation.exists():raise er.RecipeError('requires a new application generation')
    if data==generation or data in generation.parents or generation in data.parents:
        raise er.RecipeError('application bytes and retained data must be separate')
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=recipe['source']['sha256']:
            raise er.RecipeError('package checksum mismatch; no target allocated')
    if recipe['source']['medium']=='deb':
        output=subprocess.check_output(['dpkg-deb','-f',str(archive)],text=True,timeout=30)
        fields=dict(line.split(': ',1) for line in output.splitlines() if ': ' in line and not line.startswith(' '))
        if (fields.get('Package'),fields.get('Version'),fields.get('Architecture'))!=(recipe['source']['package'],recipe['source']['version'],'amd64'):
            raise er.RecipeError('native package identity does not match source lock')
    import shutil
    payload_bytes=_extract(archive,None,recipe['source']['medium'],str(Path(EXECUTABLES[recipe['app']]).parent))
    for candidate,required in ((generation,payload_bytes+256*1024**2),(data,16*1024**2)):
        existing=candidate.parent
        while not existing.exists():existing=existing.parent
        if shutil.disk_usage(existing).free<required:
            raise er.RecipeError('insufficient free space; no target allocated')
    if data.exists():
        marker=_path(data/'IDENTITY.json')
        try:identity=er.read_document(marker.read_text())
        except OSError as exc:raise er.RecipeError('retained data lacks Baseline identity') from exc
        if set(identity)!={'format','app','id'} or identity['format']!='baseline.app-state/v1' or identity['app']!=recipe['app'] or not re.fullmatch('[0-9a-f]{32}',str(identity['id'])):
            raise er.RecipeError('retained application identity mismatch')
        if not _path(data/'home').is_dir():raise er.RecipeError('retained home is missing')
    else:
        data.mkdir(mode=0o700);(data/'home').mkdir(mode=0o700)
        identity={'format':'baseline.app-state/v1','app':recipe['app'],'id':uuid.uuid4().hex}
        _write(data/'IDENTITY.json',identity)
        home=data/'home';config=home/'.config';config.mkdir(mode=0o700)
        if recipe['app']=='vscode':
            code=config/'Code';vc.stage_fresh({'format':'baseline.vscode-settings/v1','settings':recipe['configuration']},code)
        elif recipe['app']=='chrome':
            profile=config/'google-chrome'/'Default';profile.mkdir(parents=True,mode=0o700)
            homepage=recipe['configuration'].get('homepage')
            _write(profile/'Preferences',({'homepage':homepage,'homepage_is_newtabpage':False,
                    'session':{'restore_on_startup':4,'startup_urls':[homepage]}} if homepage else {}))
    generation.mkdir(mode=0o700);root=generation/'root';root.mkdir(mode=0o700)
    _extract(archive,root,recipe['source']['medium'],str(Path(EXECUTABLES[recipe['app']]).parent))
    executable=root/EXECUTABLES[recipe['app']]
    if not executable.is_file() or not os.access(executable,os.X_OK):raise er.RecipeError('native executable missing; partial generation retained')
    with (generation/'DBUS-SESSION.conf').open('x') as stream:
        os.chmod(generation/'DBUS-SESSION.conf',0o600);stream.write(PRIVATE_DBUS_CONFIG)
        stream.flush();os.fsync(stream.fileno())
    _write(generation/'BUILD.json',recipe)
    receipt={'executable':str(executable),'generation':str(generation),'data':str(data),
             'retained_identity':identity['id'],'recipe_digest':digest(recipe),
             'archive_verified':True,'runtime_verified':False,'installation':'native payload extraction; system dependencies supplied by target OS'}
    _write(generation/'INSTALL.json',receipt)
    return receipt

REPOSITORIES={
 'chrome':('https://dl.google.com/linux/chrome/deb/','dists/stable/main/binary-amd64/Packages'),
 'spotify':('https://repository.spotify.com/','dists/stable/non-free/binary-amd64/Packages'),
 'claude':('https://downloads.claude.ai/claude-desktop/apt/stable/','dists/stable/main/binary-amd64/Packages'),
}


def publisher_open(url,*,timeout):
    from urllib.request import Request,urlopen
    return urlopen(Request(url,headers={'User-Agent':'BaselineOS/0.2','Accept':'application/octet-stream'}),timeout=timeout)


def _download(url,target,opener,expected=None):
    sha=hashlib.sha256();size=0
    with opener(url,timeout=60) as response:
        if response.geturl()!=url:raise er.RecipeError('unexpected publisher redirect')
        with target.open('xb') as stream:
            os.chmod(target,0o600)
            while chunk:=response.read(1024*1024):
                size+=len(chunk)
                if size>1024**3:raise er.RecipeError('download exceeds1GiB; incomplete file retained')
                sha.update(chunk);stream.write(chunk)
            stream.flush();os.fsync(stream.fileno())
    actual=sha.hexdigest()
    if expected and actual!=expected:raise er.RecipeError('publisher checksum mismatch; unverified file retained')
    return actual


def prepare(app,configuration,destination,*,platform=None,opener=None):
    from urllib.request import urlopen
    import vscode_build as vb
    _app(app);opener=opener or publisher_open;platform=platform or target_platform()
    checked=capture(app,json.dumps(configuration))
    if checked['excluded_count']:raise er.RecipeError('unapproved configuration')
    # Validate the platform before performing network or filesystem operations.
    if platform.get('arch')!='amd64' or (platform.get('os'),platform.get('release')) not in (('ubuntu','24.04'),('ubuntu','26.04'),('debian','13')):
        raise er.RecipeError('unsupported target platform')
    destination=_path(destination)
    if destination.exists():raise er.RecipeError('requires a new download directory')
    if app=='vscode':
        locked=vb.resolve({'format':'baseline.vscode-settings/v1','settings':configuration},opener=opener)
        raw=locked['source'];source={'url':raw['url'],'sha256':raw['sha256'],'version':raw['version'],'package':'code','medium':'tar.gz'}
    elif app in REPOSITORIES:
        base,index=REPOSITORIES[app]
        with opener(base+index,timeout=30) as response:
            if response.geturl()!=base+index:raise er.RecipeError('unexpected metadata redirect')
            raw=response.read(16*1024**2+1)
            if len(raw)>16*1024**2:raise er.RecipeError('publisher index too large')
        rows=[]
        for stanza in raw.decode('utf-8').split('\n\n'):
            fields=dict(line.split(': ',1) for line in stanza.splitlines() if ': ' in line and not line.startswith(' '))
            if fields.get('Package')==PACKAGES[app] and fields.get('Architecture')=='amd64':
                version=fields.get('Version','')
                if not re.fullmatch(r'[A-Za-z0-9.+:~_-]{1,128}',version):raise er.RecipeError('invalid package version')
                rows.append(fields)
        if not rows:raise er.RecipeError('publisher has no supported package')
        chosen=rows[0]
        for candidate in rows[1:]:
            if subprocess.run(['dpkg','--compare-versions',candidate['Version'],'gt',chosen['Version']],capture_output=True).returncode==0:chosen=candidate
        source={'url':base+chosen.get('Filename',''),'sha256':chosen.get('SHA256',''),'version':chosen['Version'],'package':PACKAGES[app],'medium':'deb'}
        bind(app,configuration,source,platform)
    else:
        source={'url':'https://persistent.oaistatic.com/codex-app-prod/linux/deb/latest/chatgpt_amd64.deb','package':'chatgpt','medium':'deb'}
    destination.mkdir(mode=0o700);archive=destination/('source.tar.gz' if app=='vscode' else 'source.deb')
    sha=_download(source['url'],archive,opener,source.get('sha256'))
    if app=='chatgpt':
        text=subprocess.check_output(['dpkg-deb','-f',str(archive)],text=True,timeout=30)
        fields=dict(line.split(': ',1) for line in text.splitlines() if ': ' in line and not line.startswith(' '))
        if fields.get('Package')!='chatgpt' or fields.get('Architecture')!='amd64':raise er.RecipeError('publisher download has wrong package identity')
        source.update({'sha256':sha,'version':fields['Version']})
    return {'recipe':bind(app,configuration,source,platform),'archive':str(archive),
            'trust':'publisher HTTPS plus SHA256; no detached signature','runtime_verified':False}


def acquire(recipe,target,*,opener=None):
    from urllib.request import urlopen
    recipe=validate(recipe);target=_path(target)
    if target.exists():raise er.RecipeError('requires a new archive path')
    _download(recipe['source']['url'],target,opener or publisher_open,recipe['source']['sha256'])
    return str(target)


URI_HELPER='/opt/baseline/libexec/baseline-open-uri'
OPEN_URI_SCRIPT = '''#!/usr/bin/python3
"""Scoped web browser and publisher-declared callback protocols; no URI logging."""
import os,sys,subprocess
from pathlib import Path
from urllib.parse import urlsplit
try:
    if len(sys.argv)!=2 or len(sys.argv[1])>8192:raise ValueError()
    uri=sys.argv[1];parsed=urlsplit(uri)
    if any(ord(c)<33 for c in uri):raise ValueError()
    callbacks={'vscode':('vscode','VSCode-linux-x64/code'),'spotify':('spotify','usr/share/spotify/spotify'),
               'chatgpt':('codex','usr/lib/chatgpt/ChatGPT'),'claude':('claude','usr/lib/claude-desktop/claude-desktop')}
    source=os.environ.get('BASELINE_SOURCE_APP')
    if parsed.scheme in ('http','https'):
        if not parsed.hostname or parsed.username or parsed.password:raise ValueError()
        binary='/login-browser/opt/google/chrome/chrome'
        argv=[binary,'--user-data-dir=/home/baseline/.config/login-browser','--disable-gpu','--disable-dev-shm-usage','--no-first-run','--no-default-browser-check']
        proxy=os.environ.get('BASELINE_PROXY_URL')
        if proxy:argv+=['--proxy-server='+proxy]
    elif source in callbacks and parsed.scheme==callbacks[source][0]:
        binary='/app/root/'+callbacks[source][1]
        argv=[binary,'--disable-gpu','--disable-dev-shm-usage']
        if source=='vscode':argv+=['--user-data-dir','/home/baseline/.config/Code','--extensions-dir','/home/baseline/extensions']
    else:raise ValueError()
    if not Path(binary).is_file() or not os.access(binary,os.X_OK):raise ValueError()
    subprocess.Popen(argv+[uri],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
except (ValueError,OSError):
    print('URI dispatch refused',file=sys.stderr);sys.exit(1)
sys.exit(0)
'''


def _trusted_helper(path):
    helper=_path(path)
    for candidate in (helper,*helper.parents):
        info=candidate.stat()
        if info.st_uid!=0 or info.st_mode&0o022:
            raise er.RecipeError('runtime helper and its parents must be root-owned and not writable by users')
    return helper


def sandbox_command(generation,data,command,*,environment=None,shared=None,proxy=None,login_browser=None):
    """Filesystem/process boundary. Shared X11/audio/network are not full OS isolation."""
    generation=_path(generation);data=_path(data);environment=environment or {}
    if not generation.is_dir() or not _path(data/'home').is_dir():raise er.RecipeError('generation/private home missing')
    helper=Path('/opt/baseline/libexec/baseline-app-bwrap')
    if helper.exists():
        helper=_trusted_helper(helper)
    else:helper=Path('/usr/bin/bwrap')
    argv=[str(helper),'--die-with-parent','--new-session','--unshare-user','--unshare-pid','--unshare-ipc','--unshare-uts','--clearenv']
    for path in ('/usr','/bin','/sbin','/lib','/lib64'):
        if Path(path).exists():argv+=['--ro-bind',path,path]
    argv+=['--dir','/etc']
    for path in ('/etc/ssl','/etc/fonts','/etc/ld.so.cache','/etc/nsswitch.conf','/etc/resolv.conf','/etc/hosts','/etc/passwd','/etc/group','/etc/os-release','/etc/localtime','/etc/machine-id'):
        if Path(path).exists():argv+=['--ro-bind',path,path]
    argv+=['--proc','/proc','--dev','/dev','--tmpfs','/tmp','--dir','/run','--dir','/home',
           '--ro-bind',str(generation),'/app','--bind',str(data/'home'),'/home/baseline',
           '--setenv','HOME','/home/baseline','--setenv','PATH','/usr/bin:/bin',
           '--setenv','XDG_CONFIG_HOME','/home/baseline/.config',
           '--setenv','XDG_DATA_HOME','/home/baseline/.local/share',
           '--setenv','XDG_CACHE_HOME','/tmp/cache','--setenv','XDG_RUNTIME_DIR','/run',
           '--chdir','/home/baseline']
    if login_browser is not None:
        browser=_path(login_browser)
        if any(browser==p or browser in p.parents or p in browser.parents for p in (generation,data)):
            raise er.RecipeError('login browser code must be separate from the requesting application and data')
        browser_recipe=validate(er.read_document(_path(browser/'BUILD.json').read_text()))
        binary=_path(browser/'root'/EXECUTABLES['chrome'])
        if browser_recipe['app']!='chrome' or browser_recipe['platform']!=target_platform() or not binary.is_file() or not os.access(binary,os.X_OK):
            raise er.RecipeError('requires a native Chrome generation for this platform')
        uri_helper=_trusted_helper(URI_HELPER)
        if uri_helper.read_text()!=OPEN_URI_SCRIPT:raise er.RecipeError('web URI helper version changed; administrator update required')
        source_recipe=validate(er.read_document(_path(generation/'BUILD.json').read_text()))
        argv+=['--ro-bind',str(browser/'root'),'/login-browser','--ro-bind',str(uri_helper),'/usr/bin/xdg-open',
               '--setenv','BASELINE_SOURCE_APP',source_recipe['app']]
        if proxy is not None:argv+=['--setenv','BASELINE_PROXY_URL',_homepage(proxy)]
    if proxy is not None:
        _homepage(proxy)
        for key in ('HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy'):
            argv+=['--setenv',key,proxy]
    if environment.get('DISPLAY'):
        if not re.fullmatch(r':[0-9]+(?:\.[0-9]+)?',environment['DISPLAY']):raise er.RecipeError('only local X11 display supported')
        argv+=['--setenv','DISPLAY',environment['DISPLAY']]
        if Path('/tmp/.X11-unix').is_dir():argv+=['--ro-bind','/tmp/.X11-unix','/tmp/.X11-unix']
        auth=environment.get('XAUTHORITY')
        if auth:
            if not Path(auth).is_file():raise er.RecipeError('X11 authority unavailable')
            argv+=['--ro-bind',auth,'/run/xauthority','--setenv','XAUTHORITY','/run/xauthority']
    pulse=Path('/run/user')/str(os.getuid())/'pulse'
    if pulse.is_dir():argv+=['--ro-bind',str(pulse),'/run/audio','--setenv','PULSE_SERVER','unix:/run/audio/native']
    if shared is not None:
        shared=_path(shared)
        if not shared.is_dir() or any(shared==p or shared in p.parents or p in shared.parents for p in (generation,data)):
            raise er.RecipeError('sharing requires a separate explicit directory')
        argv+=['--bind',str(shared),'/exchange']
    return argv+['--']+list(command)


def launch(generation,data,*,shared=None,proxy=None,login_browser=None):
    import fcntl
    generation=_path(generation);data=_path(data)
    recipe=validate(er.read_document(_path(generation/'BUILD.json').read_text()))
    receipt=er.read_document(_path(generation/'INSTALL.json').read_text())
    identity=er.read_document(_path(data/'IDENTITY.json').read_text())
    if (recipe['platform']!=target_platform() or identity.get('app')!=recipe['app']
            or identity.get('id')!=receipt.get('retained_identity') or receipt.get('recipe_digest')!=digest(recipe)):
        raise er.RecipeError('platform, recipe or retained identity changed')
    if _path(generation/'DBUS-SESSION.conf').read_text()!=PRIVATE_DBUS_CONFIG:
        raise er.RecipeError('private session policy changed; new installation required')
    native='/app/root/'+EXECUTABLES[recipe['app']]
    argv=[native,'--disable-gpu','--disable-dev-shm-usage']
    if recipe['app']=='vscode':argv+=['--user-data-dir','/home/baseline/.config/Code','--extensions-dir','/home/baseline/extensions']
    elif recipe['app']=='chrome':argv+=['--user-data-dir=/home/baseline/.config/google-chrome','--no-first-run','--no-default-browser-check']
    if proxy is not None:
        _homepage(proxy);argv+=['--proxy-server='+proxy]
    if 'scale' in recipe['configuration']:argv+=['--force-device-scale-factor='+str(recipe['configuration']['scale'])]
    argv=['/usr/bin/dbus-run-session','--config-file','/app/DBUS-SESSION.conf','--']+argv
    with (data/'RUN.lock').open('a') as lock:
        os.chmod(data/'RUN.lock',0o600)
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise er.RecipeError('application already running with this retained profile') from None
        if login_browser is not None:configure_uri_handler(data,recipe['app'])
        if recipe['app']=='chrome':
            # Crash recovery may suppress Chrome's configured startup pages.
            # Open the approved current homepage explicitly without rewriting tabs.
            homepage=recipe['configuration'].get('homepage')
            preferences=_path(data/'home/.config/google-chrome/Default/Preferences')
            if preferences.is_file():
                with preferences.open() as stream:text=stream.read(1024**2+1)
                if len(text)>1024**2:raise er.RecipeError('Chrome preferences exceed launch inspection limit')
                native=er.read_document(text)
                if isinstance(native,dict) and 'homepage' in native:homepage=_homepage(native['homepage'])
            if homepage is not None:argv.append(_homepage(homepage))
        return subprocess.run(sandbox_command(generation,data,argv,environment=os.environ,shared=shared,proxy=proxy,login_browser=login_browser)).returncode


def sandbox_preflight(generation,data,*,run=subprocess.run):
    command=sandbox_command(generation,data,['/usr/bin/unshare','-Ur','/bin/true'])
    result=run(command,capture_output=True,text=True,timeout=15)
    return {'usable':result.returncode==0,
            'inner_sandbox':'nested user namespace mapping available' if result.returncode==0 else 'nested user namespace mapping unavailable',
            'scope':'namespace prerequisite only; not application launch readiness'}


def backup_state(data,target):
    import fcntl,stat,tarfile
    data=_path(data);target=_path(target)
    if target.exists() or data==target or data in target.parents:raise er.RecipeError('requires a new backup outside retained data')
    identity=er.read_document(_path(data/'IDENTITY.json').read_text())
    if identity.get('format')!='baseline.app-state/v1' or identity.get('app') not in APPS or not re.fullmatch('[0-9a-f]{32}',str(identity.get('id'))):
        raise er.RecipeError('invalid retained identity')
    home=_path(data/'home')
    excluded={'SingletonLock','SingletonSocket','SingletonCookie'}
    with (data/'RUN.lock').open('a') as lock:
        os.chmod(data/'RUN.lock',0o600)
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise er.RecipeError('stop application before backup') from None
        paths=[home]+sorted(home.rglob('*'))
        selected=[]
        for path in paths:
            if path.name in excluded:continue
            relative=path.relative_to(home).parts
            if identity['app']=='chatgpt' and relative[:2]==('.codex','tmp'):continue
            mode=path.lstat().st_mode
            if stat.S_ISSOCK(mode):continue  # Ephemeral IPC has no portable file contents.
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode) or stat.S_ISLNK(mode)):
                raise er.RecipeError('unsupported live/special file; stop application before backup')
            if path.is_symlink():
                link=os.readlink(path)
                if os.path.isabs(link) or not path.resolve().is_relative_to(home.resolve()):
                    raise er.RecipeError('external profile symlink cannot be backed up portably')
            selected.append(path)
        with target.open('xb') as stream:
            os.chmod(target,0o600)
            with tarfile.open(fileobj=stream,mode='w') as tar:
                for path in selected:tar.add(path,arcname=str(path.relative_to(data)),recursive=False)
            stream.flush();os.fsync(stream.fileno())
    with target.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'format':'baseline.application-state-backup/v1','identity':identity,'sha256':sha,
            'coverage':'stopped private home, regular files/directories/internal symlinks and modes; sockets omitted; Chromium singleton files omitted; ChatGPT .codex/tmp omitted; no ACL/xattr guarantee',
            'encrypted':False}


def restore_state(archive,manifest,target):
    import tarfile
    archive=_path(archive);target=_path(target)
    if target.exists():raise er.RecipeError('requires a new retained-data target')
    if (not isinstance(manifest,dict) or set(manifest)!={'format','identity','sha256','coverage','encrypted'}
            or manifest['format']!='baseline.application-state-backup/v1' or manifest['encrypted'] is not False):
        raise er.RecipeError('unsupported private state backup')
    identity=manifest['identity']
    if not isinstance(identity,dict) or set(identity)!={'format','app','id'} or identity['format']!='baseline.app-state/v1' or identity['app'] not in APPS or not re.fullmatch('[0-9a-f]{32}',str(identity['id'])):
        raise er.RecipeError('invalid backup identity')
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=manifest['sha256']:raise er.RecipeError('backup checksum mismatch')
        stream.seek(0)
        with tarfile.open(fileobj=stream,mode='r:') as tar:
            members=tar.getmembers();seen=set();size=0
            for member in members:
                if not (member.name=='home' or member.name.startswith('home/')) or member.name in seen:
                    raise er.RecipeError('unexpected backup member')
                seen.add(member.name);size+=member.size
                if len(seen)>100000 or size>8*1024**3:raise er.RecipeError('backup exceeds supported restore limits')
                try:tarfile.data_filter(member,str(target))
                except tarfile.FilterError as exc:raise er.RecipeError('unsafe backup path') from exc
            target.mkdir(mode=0o700);tar.extractall(target,members=members,filter='data')
    if not (target/'home').is_dir():raise er.RecipeError('backup lacks private home; incomplete restore retained')
    _write(target/'IDENTITY.json',identity)
    return identity

RUNTIME_HELPER='/opt/baseline/libexec/baseline-app-bwrap'


def runtime_plan(platform):
    if platform.get('arch')!='amd64' or (platform.get('os'),platform.get('release')) not in (('ubuntu','24.04'),('ubuntu','26.04'),('debian','13')):
        raise er.RecipeError('unsupported runtime platform')
    packages=['bubblewrap','dbus','python3','xdg-utils','libgtk-3-0','libnotify4','libnss3','libatspi2.0-0',
              'libdrm2','libgbm1','libxcb-dri3-0','libsecret-1-0','libglib2.0-bin','libxtst6','libuuid1',
              'xdg-desktop-portal','xdg-desktop-portal-gtk','libasound2t64','libatk-bridge2.0-0',
              'libatomic1','libxshmfence1','libxss1','libayatana-appindicator3-1','fonts-liberation',
              'libcurl4t64','libvulkan1','libxkbcommon0','libxrandr2']
    profile='''abi <abi/4.0>,
include <tunables/global>
profile baseline-app-runtime /opt/baseline/libexec/baseline-app-bwrap flags=(unconfined) {
  userns,
}
'''
    return {'helper':RUNTIME_HELPER,'uri_helper':URI_HELPER,'packages':packages,'apparmor_profile':profile,
            'scope':'root-owned namespace helper; filesystem policy is enforced by Bubblewrap arguments; shared X11/audio/network remain outside a complete phone-OS isolation claim'}


def install_runtime(*,update=False):
    import shutil
    if os.geteuid()!=0:raise er.RecipeError('runtime prerequisites require the installer administrator; no credential accepted by this tool')
    plan=runtime_plan(target_platform())
    subprocess.run(['apt-get','update'],check=True)
    subprocess.run(['apt-get','install','-y','--no-install-recommends']+plan['packages'],check=True,
                   env={**os.environ,'DEBIAN_FRONTEND':'noninteractive'})
    helper=_path(plan['helper']);helper.parent.mkdir(parents=True,exist_ok=True,mode=0o755)
    install_helper(helper,Path('/usr/bin/bwrap').read_bytes(),update=update)
    install_helper(URI_HELPER,OPEN_URI_SCRIPT.encode(),update=update)
    profile=_path('/etc/apparmor.d/baseline-app-runtime')
    if shutil.which('apparmor_parser') and Path('/sys/module/apparmor').exists():
        if profile.exists() and profile.read_text()!=plan['apparmor_profile']:
            raise er.RecipeError('runtime AppArmor policy changed; separate policy review required')
        if not profile.exists():
            with profile.open('x') as stream:stream.write(plan['apparmor_profile'])
        subprocess.run(['apparmor_parser','-r',str(profile)],check=True)
    versions=subprocess.check_output(['dpkg-query','-W','-f=${Package}=${Version}\n']+plan['packages'],text=True)
    return {'helper':str(helper),'dependencies_installed':versions.splitlines(),'runtime_verified':False}


def capture_installed(generation,data):
    """Extract the implemented configuration layer; never export an opaque profile.

    VS Code and Chrome read native allowlisted files. Other adapters currently
    extract Baseline launch options only; this is stated in the result.
    """
    import fcntl
    generation=_path(generation);data=_path(data)
    recipe=validate(er.read_document(_path(generation/'BUILD.json').read_text()))
    receipt=er.read_document(_path(generation/'INSTALL.json').read_text())
    identity=er.read_document(_path(data/'IDENTITY.json').read_text())
    if (not isinstance(identity,dict) or set(identity)!={'format','app','id'}
            or identity['format']!='baseline.app-state/v1' or identity['app']!=recipe['app']
            or not re.fullmatch('[0-9a-f]{32}',str(identity['id']))
            or receipt.get('retained_identity')!=identity['id'] or receipt.get('recipe_digest')!=digest(recipe)):
        raise er.RecipeError('installed recipe or retained identity changed')
    with (data/'RUN.lock').open('a') as lock:
        os.chmod(data/'RUN.lock',0o600)
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise er.RecipeError('stop application before capture') from None
        app=recipe['app'];configuration=dict(recipe['configuration']);excluded=0
        paths={'vscode':'.config/Code/User/settings.json','chrome':'.config/google-chrome/Default/Preferences'}
        coverage='Baseline launch options only; native preference extraction not implemented for this adapter'
        if app in paths:
            path=_path(data/'home'/paths[app])
            with path.open() as stream:text=stream.read(65537)
            captured=capture(app,text);excluded=captured['excluded_count']
            if app=='vscode':configuration=captured['configuration']
            else:
                if 'homepage' in captured['configuration']:configuration['homepage']=captured['configuration']['homepage']
            coverage='native allowlisted configuration plus Baseline launch options'
        captured_recipe=bind(app,configuration,recipe['source'],recipe['platform'])
    return {'recipe':captured_recipe,'coverage':coverage,'excluded_count':excluded,
            'opaque_profile_exported':False,'runtime_verified':False}


def apply_configuration(data,configuration):
    """Explicit stopped-profile native apply, preserving unselected preferences."""
    import fcntl,tempfile
    data=_path(data);identity=er.read_document(_path(data/'IDENTITY.json').read_text())
    if (not isinstance(identity,dict) or set(identity)!={'format','app','id'}
            or identity['format']!='baseline.app-state/v1'
            or not re.fullmatch('[0-9a-f]{32}',str(identity['id']))):
        raise er.RecipeError('invalid retained identity')
    app=identity['app'];approved=capture(app,json.dumps(configuration))
    if approved['excluded_count']:raise er.RecipeError('unapproved native configuration')
    if app not in ('vscode','chrome') or (app=='chrome' and set(configuration)-{'homepage'}):
        raise er.RecipeError('native apply supports VS Code settings and Chrome homepage; launch options require a new generation')
    relative='.config/Code/User/settings.json' if app=='vscode' else '.config/google-chrome/Default/Preferences'
    path=_path(data/'home'/relative)
    with (data/'RUN.lock').open('a') as lock:
        os.chmod(data/'RUN.lock',0o600)
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise er.RecipeError('stop application before apply') from None
        with path.open() as stream:text=stream.read(65537)
        native=er.read_document(vc._jsonc(text) if app=='vscode' else text)
        if not isinstance(native,dict):raise er.RecipeError('native preferences must be an object')
        if app=='vscode':native.update(approved['configuration'])
        elif 'homepage' in configuration:
            homepage=approved['configuration']['homepage']
            session=native.get('session',{})
            if not isinstance(session,dict):raise er.RecipeError('unsupported native Chrome session structure')
            native.update({'homepage':homepage,'homepage_is_newtabpage':False})
            session.update({'restore_on_startup':4,'startup_urls':[homepage]});native['session']=session
        fd,name=tempfile.mkstemp(prefix='.baseline-config-',dir=path.parent)
        with os.fdopen(fd,'w') as stream:
            json.dump(native,stream,sort_keys=True,indent=2);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
        directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
    return {'app':app,'changed_keys':sorted(configuration),'native_file_updated':True,'runtime_verified':False}


def compose(recipes):
    if not isinstance(recipes,list) or not 1<=len(recipes)<=len(APPS):raise er.RecipeError('suite requires a nonempty supported application list')
    recipes=[validate(recipe) for recipe in recipes]
    platform=recipes[0]['platform'];seen=set()
    for recipe in recipes:
        if recipe['app'] in seen or recipe['platform']!=platform:raise er.RecipeError('duplicate app or incompatible suite platform')
        seen.add(recipe['app'])
    document={'format':'baseline.application-suite/v1','platform':platform,'applications':sorted(recipes,key=lambda r:r['app'])}
    document['digest']=hashlib.sha256(json.dumps(document,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return document


def validate_suite(document):
    if not isinstance(document,dict) or set(document)!={'format','platform','applications','digest'}:
        raise er.RecipeError('unsupported application suite')
    checked=compose(document['applications'])
    if checked!=document:raise er.RecipeError('suite format, platform, order or digest changed')
    return checked


def retarget_suite(document,platform):
    suite=validate_suite(document)
    return compose([bind(r['app'],r['configuration'],r['source'],platform) for r in suite['applications']])


def build_suite(document,cache,generation,data):
    """Rebuild application bytes from locks while retaining separate private homes.

    Cache is caller-selected vanilla package storage; the desired suite is a
    separate preferences artifact. No GUI/account readiness is inferred.
    """
    import shutil
    suite=validate_suite(document)
    if suite['platform']!=target_platform():raise er.RecipeError('suite target platform differs from this OS')
    cache=_path(cache);generation=_path(generation);data=_path(data)
    paths=(cache,generation,data)
    for i,path in enumerate(paths):
        if any(path==other or path in other.parents or other in path.parents for other in paths[i+1:]):
            raise er.RecipeError('cache, generations and private data must be structurally separate')
    if generation.exists():raise er.RecipeError('requires a new suite generation')
    cache.mkdir(mode=0o700,exist_ok=True)
    archives={};required=256*1024**2
    for recipe in suite['applications']:
        source=recipe['source'];archive=_path(cache/(source['sha256']+('.tar.gz' if source['medium']=='tar.gz' else '.deb')))
        if not archive.exists():acquire(recipe,archive)
        with archive.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=source['sha256']:raise er.RecipeError('cached package checksum mismatch')
        required+=_extract(archive,None,source['medium'],str(Path(EXECUTABLES[recipe['app']]).parent))
        archives[recipe['app']]=archive
    existing=generation.parent
    while not existing.exists():existing=existing.parent
    if shutil.disk_usage(existing).free<required:raise er.RecipeError('insufficient space for the complete suite; no generation allocated')
    generation.mkdir(mode=0o700);data.mkdir(mode=0o700,exist_ok=True)
    _write(generation/'SUITE.json',suite)
    results={}
    try:
        for recipe in suite['applications']:
            app=recipe['app'];results[app]=install(recipe,archives[app],generation/app,data/app)
    except Exception as exc:
        _write(generation/'FAILURE.json',{'completed_applications':sorted(results),'error':str(exc),'scope':'incomplete generation retained; choose a new generation to retry'})
        raise
    receipt={'suite_digest':suite['digest'],'applications':results,'runtime_verified':False}
    _write(generation/'INSTALL.json',receipt)
    return receipt


URI_SCHEMES={'vscode':'vscode','spotify':'spotify','chatgpt':'codex','claude':'claude'}


def configure_uri_handler(data,app):
    """Register only this app's callback inside its private XDG directories."""
    import configparser,tempfile
    _app(app)
    if app not in URI_SCHEMES:raise er.RecipeError('this app has no declared native callback')
    data=_path(data);home=_path(data/'home')
    directory=_path(home/'.local/share/applications');directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    entry=_path(directory/'baseline-app-uri.desktop')
    text='[Desktop Entry]\nType=Application\nName=Baseline '+app+' callback\nExec=/usr/bin/xdg-open %u\nNoDisplay=true\nMimeType=x-scheme-handler/'+URI_SCHEMES[app]+';\n'
    with entry.open('w') as stream:os.chmod(entry,0o600);stream.write(text);stream.flush();os.fsync(stream.fileno())
    defaults=_path(home/'.config/mimeapps.list');defaults.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    document=configparser.ConfigParser(interpolation=None)
    try:
        if defaults.exists():
            if defaults.stat().st_size>65536:raise er.RecipeError('native MIME defaults exceed supported size')
            document.read_string(defaults.read_text())
    except configparser.Error:raise er.RecipeError('unsupported native MIME defaults') from None
    if not document.has_section('Default Applications'):document.add_section('Default Applications')
    document.set('Default Applications','x-scheme-handler/'+URI_SCHEMES[app],'baseline-app-uri.desktop;')
    fd,name=tempfile.mkstemp(prefix='.baseline-mime-',dir=defaults.parent)
    with os.fdopen(fd,'w') as stream:document.write(stream);stream.flush();os.fsync(stream.fileno())
    os.replace(name,defaults)


def install_helper(path,payload,*,update=False):
    """Administrator-reviewed atomic helper replacement; existing inode stays valid."""
    import tempfile
    if os.geteuid()!=0:raise er.RecipeError('runtime helper installation requires administrator')
    path=_path(path)
    if path.exists():
        if not path.is_file():raise er.RecipeError('runtime helper must be a regular file')
        _trusted_helper(path)
        if path.read_bytes()==payload:return
        if not update:raise er.RecipeError('runtime helper version changed; explicit administrator update required')
    fd,name=tempfile.mkstemp(prefix='.baseline-helper-',dir=path.parent)
    with os.fdopen(fd,'wb') as stream:
        os.fchmod(stream.fileno(),0o755);stream.write(payload);stream.flush();os.fsync(stream.fileno())
    os.replace(name,path)
    directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(directory)
    finally:os.close(directory)
    _trusted_helper(path)


def desktop_launchers(generation,data,target,*,cli=None):
    """Create freedesktop launch entries for a completed suite; no implicit sharing."""
    generation=_path(generation);data=_path(data);target=_path(target)
    suite=validate_suite(er.read_document((generation/'SUITE.json').read_text()))
    receipt=er.read_document((generation/'INSTALL.json').read_text())
    apps={recipe['app'] for recipe in suite['applications']}
    if receipt.get('suite_digest')!=suite['digest'] or set(receipt.get('applications',{}))!=apps:
        raise er.RecipeError('suite installation receipt mismatch')
    cli=_path(cli or Path(__file__).resolve().parent.parent/'bin/baseline-apps')
    if not cli.is_file() or not os.access(cli,os.X_OK):raise er.RecipeError('application launcher unavailable')
    if not data.is_dir():raise er.RecipeError('private state directory unavailable')
    def argument(value):
        value=str(value)
        if any(ord(char)<32 or ord(char)==127 for char in value):raise er.RecipeError('control character in launcher path')
        value=value.replace('%','%%')
        for char in ('\\','"','`','$'):value=value.replace(char,'\\'+char)
        return '"'+value+'"'
    entries={}
    names={'chrome':'Chrome','vscode':'VS Code','spotify':'Spotify','chatgpt':'ChatGPT','claude':'Claude Desktop'}
    for app in sorted(apps):
        command=' '.join(argument(value) for value in (cli,'launch',generation/app,data/app))
        entries[app]='[Desktop Entry]\nType=Application\nName=Baseline '+names[app]+'\nExec='+command+'\nTerminal=false\nCategories=Utility;\n'
    if target.exists():raise er.RecipeError('requires a new launcher directory')
    target.mkdir(mode=0o700,parents=True)
    for app,text in entries.items():
        with (target/('baseline-'+app+'.desktop')).open('x') as stream:
            os.chmod(stream.name,0o600);stream.write(text);stream.flush();os.fsync(stream.fileno())
    return {'entries':{app:str(target/('baseline-'+app+'.desktop')) for app in entries},'runtime_verified':False}
