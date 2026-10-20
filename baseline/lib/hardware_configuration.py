"""Real PCI driver selection for host or managed Proxmox guests."""
import re
from types import SimpleNamespace
import html
import json


def driver_choices(runner,address):
    if not re.fullmatch(r'[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]',address):
        raise RuntimeError('Invalid PCI address')
    text=runner.read_text('/sys/bus/pci/devices/'+address+'/uevent')
    facts=dict(line.split('=',1) for line in text.splitlines() if '=' in line)
    alias=facts.get('MODALIAS')
    if not alias or not alias.startswith('pci:'):
        raise RuntimeError('Device module alias unavailable; no driver choices inferred')
    result=runner.run(['modprobe','--resolve-alias',alias],timeout=15)
    if result.returncode:
        raise RuntimeError('Compatible installed module discovery failed: '+result.stderr.strip())
    modules=result.stdout.split()
    if any(not re.fullmatch(r'[a-zA-Z0-9_]+',module) for module in modules):
        raise RuntimeError('Malformed native module discovery')
    return {'pci_id':facts.get('PCI_ID','').lower(),'driver':facts.get('DRIVER'), 'modules':modules}


def load_driver(runner,*,address,pci_id,module):
    facts=driver_choices(runner,address)
    if facts['pci_id']!=pci_id.lower():raise RuntimeError('Device identity changed')
    if module not in facts['modules']:raise RuntimeError('Select a compatible installed module')
    result=runner.run(['modprobe',module],timeout=30)
    if result.returncode:raise RuntimeError('Driver load failed: '+result.stderr.strip())
    observed=driver_choices(runner,address)
    if observed['pci_id']!=pci_id.lower():raise RuntimeError('Device identity changed during load')
    if not observed['driver']:raise RuntimeError('Module loaded but device is not bound; no success inferred')
    ownership=runner.run(['readlink','-f','--','/sys/bus/pci/devices/'+address+'/driver/module'],timeout=15)
    owner=ownership.stdout.strip()
    if ownership.returncode or not re.fullmatch(r'/sys/module/[a-zA-Z0-9_]+',owner):
        raise RuntimeError('Bound driver module ownership unavailable; no success inferred')
    if owner.rsplit('/',1)[-1] != module:
        raise RuntimeError('Device binding did not apply the requested module '+module+'; observed '+owner)
    return {'outcome':'applied','detail':'Device is bound to '+observed['driver']+' (module '+module+')', 'driver':observed['driver'], 'module':module}


class GuestRunner:
    """Uses the native adapter's guarded guest agent, never the host shell."""
    def __init__(self,host,name):
        if not callable(getattr(host,'guest_exec',None)):
            raise RuntimeError('Guest driver configuration requires the native managed Proxmox guest adapter')
        self.host,self.name=host,name

    def run(self,argv,timeout=15):
        native=self.host.guest_exec(self.name,argv)
        if not isinstance(native,dict) or 'exitcode' not in native:
            raise RuntimeError('Guest command has no observed exit status')
        return SimpleNamespace(returncode=native['exitcode'],stdout=native.get('out-data',''),stderr=native.get('err-data',''))

    def read_text(self,path):
        result=self.run(['cat','--',path])
        if result.returncode:raise RuntimeError('Guest file observation failed: '+result.stderr)
        return result.stdout



def module_package(runner,module):
    """Observe ownership of the installed module binary; never infer a package."""
    try:
        if not re.fullmatch(r'[a-zA-Z0-9_-]+',module):
            raise RuntimeError('Invalid observed module name')
        result=runner.run(['modinfo','--filename',module],timeout=15)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'Module binary discovery failed')
        path=result.stdout.strip()
        if path == '(builtin)':
            return {'packages':[], 'builtin':True, 'path':path}
        if not path.startswith(('/lib/modules/','/usr/lib/modules/')) or '\n' in path:
            raise RuntimeError('Module binary path unavailable')
        owner=runner.run(['dpkg-query','--search',path],timeout=15)
        if owner.returncode:
            raise RuntimeError(owner.stderr.strip() or 'No package owns this module binary')
        names=[]
        for line in owner.stdout.splitlines():
            if ': ' not in line:raise RuntimeError('Malformed package ownership response')
            packages,owned_path=line.rsplit(': ',1)
            if owned_path != path:continue
            for package in packages.split(', '):
                if not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*(?::[a-z0-9_-]+)?',package):
                    raise RuntimeError('Malformed package identity')
                if package not in names:names.append(package)
        if not names:raise RuntimeError('No exact module binary ownership observed')
        return {'packages':names,'path':path,'builtin':False}
    except Exception as exc:
        return {'packages':[],'error':str(exc)}

def render_driver_controls(runner,devices,target='',module_packages=None):
    rows=[]
    module_packages={} if module_packages is None else module_packages
    for device in devices:
        try:
            facts=driver_choices(runner,device.address)
            options=''.join(f'<option>{html.escape(module)}</option>' for module in facts['modules'])
            status='Bound to '+facts['driver'] if facts['driver'] else 'No driver bound'
            if options:
                signed=html.escape(json.dumps({'address':device.address,'pci_id':facts['pci_id'],'vm':target}),quote=True)
                control=(f'<form data-driver-request="{signed}"><label>Installed compatible driver '
                         f'<select name="module">{options}</select></label><button type="submit">Load driver</button>'
                         '<span role="status"></span></form>')
            else:
                control='No compatible installed module found. Check the installer cache for driver packages.'
        except Exception as exc:
            status='Driver discovery unavailable: '+str(exc);control='No driver action offered.'
        package_html=''
        if device.kernel_driver:
            if device.kernel_driver not in module_packages:
                module_packages[device.kernel_driver]=module_package(runner,device.kernel_driver)
            ownership=module_packages[device.kernel_driver]
            if ownership.get('builtin'):
                package_html='<p>Driver is built into this kernel; no separate module binary.</p>'
            elif ownership['packages']:
                import installer_cache
                from urllib.parse import quote
                catalog_ids={entry.entry_id for entry in installer_cache.catalog()}
                packages=[]
                for package in ownership['packages']:
                    label=html.escape(package)
                    package_id=package.split(':',1)[0]
                    if package_id in catalog_ids:
                        label+='<a href="/installer-cache#cache-entry-'+quote(package_id,safe='')+'"> Installer and source</a>'
                    else:
                        label+=' (not yet declared in Installer Cache)'
                    packages.append(label)
                package_html='<p>Installed driver package: '+', '.join(packages)+'</p>'
            else:
                package_html='<p role="alert">Driver package ownership unavailable: '+html.escape(ownership.get('error','Unknown ownership'))+'</p>'
        rows.append(f'<details><summary>{html.escape(device.model)} — {html.escape(status)}</summary>'
            f'<p>{html.escape(device.address)} · {html.escape(device.pci_id)}</p>{package_html}{control}'
            '<details><summary aria-label="About driver loading">ⓘ</summary><p>Choices come from this device’s kernel module alias. Loading a module does not unload an existing driver or assign the device to a VM. The result verifies actual driver binding. Guest actions use the selected guest’s kernel.</p></details></details>')
    return '<h2>Device driver configuration</h2>'+(''.join(rows) or '<p>No configurable PCI devices were observed.</p>')+'''<script>
for(const form of document.querySelectorAll('[data-driver-request]'))form.onsubmit=async event=>{
 event.preventDefault();const status=form.querySelector('[role=status]'),button=form.querySelector('button');button.disabled=true;
 try{const body=JSON.parse(form.dataset.driverRequest);body.module=form.elements.module.value;
 const response=await fetch('/hardware/driver',{method:'POST',credentials:'same-origin',referrerPolicy:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const result=await response.json();status.textContent=result.detail||result.error||'Driver request failed';
 }catch(error){status.textContent='Driver request failed: '+error.message;}finally{button.disabled=false;}
};</script>'''
