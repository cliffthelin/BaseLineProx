#!/usr/bin/python
"""Root prerequisite task, separate from non-root private application builds."""
import hashlib
import json
import os
from ansible.module_utils.basic import AnsibleModule
from ansible_collections.baseline.environment.plugins.module_utils.backend import verify_backend

DOCUMENTATION = r'''
module: native_runtime
short_description: Install Baseline native application prerequisites
options:
  platform: {description: Expected exact OS release and architecture, type: dict, required: true}
  update: {description: Explicitly update root-owned helper bytes, type: bool, default: false}
'''


def main():
    module=AnsibleModule(argument_spec={'backend_sha256':{'type':'dict','required':True},'platform':{'type':'dict','required':True},'update':{'type':'bool','default':False}},supports_check_mode=True)
    backend=verify_backend(module,module.params['backend_sha256'])
    executable='/opt/baseline/bin/baseline-apps'
    def call(action,*args):
        code,out,err=module.run_command([executable,action,*args])
        if code:module.fail_json(msg='Baseline '+action+' refused',rc=code,stderr=err)
        try:return json.loads(out)
        except ValueError:module.fail_json(msg='Baseline returned invalid prerequisite result')
    plan=call('runtime-plan')
    if plan['platform']!=module.params['platform']:module.fail_json(msg='Prerequisite target differs from requested OS')
    if module.check_mode:module.exit_json(changed=True,msg='Supported prerequisite plan; package resolution/install not executed')
    if os.geteuid()!=0:module.fail_json(msg='Prerequisites require administrator execution')
    def fingerprint():
        values={}
        for path in (plan['helper'],plan['uri_helper'],'/etc/apparmor.d/baseline-app-runtime'):
            if os.path.isfile(path):
                with open(path,'rb') as stream:values[path]=hashlib.file_digest(stream,'sha256').hexdigest()
        code,out,_=module.run_command(['dpkg-query','-W','-f=${Package}=${Version}\n',*plan['packages']])
        values['dependencies']=out if code==0 else None
        return values
    before=fingerprint();report=call('install-runtime',*(['--update'] if module.params['update'] else []));after=fingerprint()
    code,virtualization,_=module.run_command(['systemd-detect-virt','--vm'])
    environment={'kernel':os.uname().release,'virtualization':virtualization.strip() if code==0 else 'not-detected'}
    module.exit_json(changed=before!=after,compatibility={'backend_sha256':backend,'environment':environment,'component':'baseline.environment.native_runtime',
        'platform':plan['platform'],'applications':{},'capability':'dependencies-installed',
        'dependencies':report['dependencies_installed'],'runtime_verified':False})


if __name__=='__main__':main()
