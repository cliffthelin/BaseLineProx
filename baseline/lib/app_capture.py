"""Read-only installed-deb inspection, not a recipe or clean-install proof."""
import re
import vm_host as vh

FORMAT='${db:Status-Status}\n${Package}\n${Version}\n${Architecture}\n${Depends}\n${Conffiles}\n'


def inspect_vm(host,name,package):
    if not isinstance(package,str) or not re.fullmatch(r'[a-z0-9][a-z0-9+.-]{0,99}',package):
        raise vh.VmError('choose a single Debian package name; patterns and options are refused')
    if not callable(getattr(host,'guest_exec',None)):
        raise vh.VmError('installed-app inspection requires a managed running Ubuntu/Proxmox VM')
    native=host.guest_exec(name,['dpkg-query','--show','--showformat='+FORMAT,package])
    text=native.get('out-data','') if isinstance(native,dict) else ''
    if not isinstance(text,str) or len(text)>32768:
        raise vh.VmError('guest package report is missing or exceeds the supported size')
    fields=text.split('\n',5)
    if len(fields)!=6 or fields[0]!='installed' or fields[1]!=package:
        raise vh.VmError('package is not installed or its native identity changed')
    _,_,version,arch,depends,conffiles=fields
    if not re.fullmatch(r'[A-Za-z0-9.+:~_-]{1,128}',version) or arch not in ('amd64','all'):
        raise vh.VmError('unsupported package version or architecture')
    if len(depends)>8192 or any(ord(c)<32 or ord(c)==127 for c in depends):
        raise vh.VmError('invalid dependency metadata')
    paths=[]
    for line in conffiles.splitlines():
        if not line.strip():continue
        match=re.fullmatch(r' (/etc/[^\s]+) [0-9a-f]{32}(?: obsolete)?',line)
        if not match or '..' in match.group(1).split('/'):
            raise vh.VmError('unsupported configuration path metadata; no contents extracted')
        paths.append(match.group(1))
    report={'format':'baseline.app-inspection/v1','medium':'deb','package':package,
            'version':version,'architecture':arch,'dependencies_declared':depends,
            'configuration_paths':paths,'contents_extracted':False,'sources_verified':False,
            'recipe_ready':False,'test_install_verified':False,'state_coverage':'unknown',
            'remaining':['verify reacquirable installation source and dependency lock',
                         'app-specific settings exporter and state/permission declaration',
                         'review reusable configuration before recipe promotion',
                         'clean-target install/apply/launch and retention tests']}
    return {'ok':True,'capture_report':report,
            'message':'Installed package inspected; no configuration contents copied. Recipe and test install remain unverified.'}
