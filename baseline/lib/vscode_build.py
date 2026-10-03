"""Linux x64 VS Code byte lock, acquisition and fresh-directory materialization.

HTTPS publisher metadata plus SHA256; no detached signature or VM isolation proof.
"""
import hashlib
import json
import re
from pathlib import Path
from urllib.request import urlopen
import environment_recipes as er
import vscode_capture as vc

API='https://update.code.visualstudio.com/api/update/linux-x64/stable/latest'
URL=re.compile(r'https://vscode\.download\.prss\.microsoft\.com/dbazure/download/stable/([0-9a-f]{40})/code-stable-x64-[0-9]+\.tar\.gz')


def bind(settings,metadata):
    vc.export(settings)
    if not isinstance(metadata,dict):raise er.RecipeError('invalid publisher metadata')
    commit=metadata.get('version');url=metadata.get('url');sha=metadata.get('sha256hash');version=metadata.get('productVersion')
    match=URL.fullmatch(url) if isinstance(url,str) else None
    if (not match or match.group(1)!=commit or not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha)
            or not isinstance(version,str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',version)):
        raise er.RecipeError('unsupported publisher source identity')
    return json.loads(json.dumps({'format':'baseline.vscode-build/v1','platform':'linux-x64',
            'source':{'version':version,'commit':commit,'url':url,'sha256':sha},'settings':settings}))


def validate(build):
    if (not isinstance(build,dict) or set(build)!={'format','platform','source','settings'}
            or build['format']!='baseline.vscode-build/v1' or build['platform']!='linux-x64'
            or not isinstance(build['source'],dict) or set(build['source'])!={'version','commit','url','sha256'}):
        raise er.RecipeError('unsupported VS Code build')
    source=build['source']
    return bind(build['settings'],{'productVersion':source['version'],'version':source['commit'],
                                  'url':source['url'],'sha256hash':source['sha256']})


def resolve(settings,opener=urlopen):
    with opener(API,timeout=30) as response:
        if response.geturl()!=API:raise er.RecipeError('publisher metadata redirected unexpectedly')
        metadata=er.read_document(response.read(65537).decode('utf-8'))
    return bind(settings,metadata)


def _new(path):
    path=Path(path)
    if path.exists() or path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise er.RecipeError('requires an unused destination without symlink ancestors')
    return path


def fetch(build,target,opener=urlopen):
    import os
    build=validate(build);target=_new(target);source=build['source'];sha=hashlib.sha256();size=0
    with opener(source['url'],timeout=60) as response:
        if response.geturl()!=source['url']:raise er.RecipeError('archive redirected unexpectedly')
        with target.open('xb') as stream:
            os.chmod(target,0o600)
            while chunk:=response.read(1024*1024):
                size+=len(chunk)
                if size>512*1024*1024:raise er.RecipeError('archive exceeds512MiB; incomplete file retained')
                stream.write(chunk);sha.update(chunk)
            stream.flush();os.fsync(stream.fileno())
    if sha.hexdigest()!=source['sha256']:
        raise er.RecipeError('archive checksum mismatch; unverified file retained, do not install')
    return target


def install(build,archive,target):
    import tarfile
    import os
    build=validate(build);archive=Path(archive);target=_new(target)
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=build['source']['sha256']:
            raise er.RecipeError('archive checksum mismatch; no target allocated')
        stream.seek(0)
        with tarfile.open(fileobj=stream,mode='r:gz') as tar:
            members=tar.getmembers();size=0;seen=set()
            if len(members)>20000:raise er.RecipeError('archive has too many entries')
            for member in members:
                parts=Path(member.name).parts
                if (not parts or parts[0]!='VSCode-linux-x64' or member.name in seen
                        or not (member.isfile() or member.isdir() or member.issym() or member.islnk())):
                    raise er.RecipeError('unexpected archive entry')
                seen.add(member.name);size+=member.size
                if size>2*1024*1024*1024:raise er.RecipeError('unpacked archive exceeds2GiB')
                try:tarfile.data_filter(member,str(target/'application'))
                except tarfile.FilterError as exc:raise er.RecipeError('unsafe archive path') from exc
            target.mkdir(mode=0o700);app=target/'application';app.mkdir(mode=0o700)
            tar.extractall(app,members=members,filter='data')
    executable=app/'VSCode-linux-x64/bin/code'
    if not executable.is_file() or not os.access(executable,os.X_OK):
        raise er.RecipeError('archive lacks executable; incomplete target retained')
    vc.stage_fresh(build['settings'],target/'profile')
    (target/'extensions').mkdir(mode=0o700)
    with (target/'BUILD.json').open('x') as file:
        os.chmod(target/'BUILD.json',0o600);json.dump(build,file,sort_keys=True,indent=2)
        file.flush();os.fsync(file.fileno())
    return {'executable':str(executable),'profile':str(target/'profile'),
            'extensions':str(target/'extensions'),'archive_verified':True,'runtime_verified':False}
