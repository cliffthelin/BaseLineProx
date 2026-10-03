#!/usr/bin/python
"""Ansible adapter to the installed Baseline CLI. No shell or AI execution."""
import json
import os
import tempfile
from ansible.module_utils.basic import AnsibleModule
from ansible_collections.baseline.environment.plugins.module_utils.backend import verify_backend

DOCUMENTATION = r'''
module: native_suite
short_description: Build a pinned native suite and inspect retained identities
options:
  suite: {description: Configuration-only locked suite, type: dict, required: true}
  cache: {description: Separate raw package cache, type: path, required: true}
  generation: {description: New generation or matching completed generation, type: path, required: true}
  data: {description: Separate retained per-app private state, type: path, required: true}
'''


def main():
    module=AnsibleModule(argument_spec={
        'backend_sha256':{'type':'dict','required':True},
        'suite':{'type':'dict','required':True},
        'cache':{'type':'path','required':True},
        'generation':{'type':'path','required':True},
        'data':{'type':'path','required':True}},supports_check_mode=True)
    backend=verify_backend(module,module.params['backend_sha256'])
    executable='/opt/baseline/bin/baseline-apps'
    if not os.path.isfile(executable) or not os.access(executable,os.X_OK):
        module.fail_json(msg='Baseline application CLI is not installed on this target')
    fd,path=tempfile.mkstemp(prefix='baseline-suite-',suffix='.json',dir=module.tmpdir)
    with os.fdopen(fd,'w') as stream:json.dump(module.params['suite'],stream)
    def call(action,*args):
        code,out,err=module.run_command([executable,action,path,*args])
        if code:module.fail_json(msg='Baseline '+action+' refused',rc=code,stderr=err)
        try:return json.loads(out)
        except ValueError:module.fail_json(msg='Baseline returned an invalid result')
    call('verify-suite')
    code,out,err=module.run_command([executable,'runtime-plan'])
    if code:module.fail_json(msg='Unsupported application target',rc=code,stderr=err)
    try:platform=json.loads(out)['platform']
    except (ValueError,KeyError):module.fail_json(msg='Invalid target platform result')
    if platform!=module.params['suite']['platform']:module.fail_json(msg='Application target differs from recipe OS')
    existing=os.path.lexists(module.params['generation'])
    if existing:
        report=call('inspect-suite',module.params['generation'],module.params['data'])
        changed=False
    elif module.check_mode:
        module.exit_json(changed=True,msg='Validated recipe; new generation would be built; no native installation or compatibility proof')
    else:
        call('build-suite',module.params['generation'],module.params['data'],'--cache',module.params['cache'])
        report=call('inspect-suite',module.params['generation'],module.params['data'])
        changed=True
    code,virtualization,_=module.run_command(['systemd-detect-virt','--vm'])
    environment={'kernel':os.uname().release,'virtualization':virtualization.strip() if code==0 else 'not-detected'}
    compatibility={'backend_sha256':backend,'environment':environment,'component':'baseline.environment.native_suite','platform':report['platform'],
        'suite_digest':report['suite_digest'],'applications':report['applications'],
        'capability':'materialized','runtime_verified':False,'coverage':report['coverage']}
    # Check-mode inspection is useful, but does not create a new execution attestation.
    module.exit_json(changed=changed,compatibility=compatibility if not module.check_mode else None,
                     materialized=True,runtime_verified=False)


if __name__=='__main__':main()
