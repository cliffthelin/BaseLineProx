"""Read-only installer plan editor; never executes compiled stages."""
import json
import install_plan as ip


def perform(body, *, discovery_provider):
    if not isinstance(body,dict) or body.get('action') not in ('autofill','validate','compile','map_appdata'):
        raise ip.PlanError('unsupported installer plan action')
    required={'action'} if body['action']=='autofill' else {'action','plan'}
    if body['action']=='map_appdata':required={'action','plan','persona','serial','partuuid'}
    if set(body)!=required:raise ip.PlanError('unsupported or missing installer plan fields')
    if 'plan' in body:
        try:size=len(json.dumps(body['plan'],ensure_ascii=False,allow_nan=False).encode('utf-8'))
        except (ValueError,TypeError,RecursionError):raise ip.PlanError('plan must contain JSON values') from None
        if size>65536:raise ip.PlanError('plan exceeds 64 KiB')
    found=discovery_provider()
    if body['action']=='autofill':
        plan=ip.autofill(found)
    else:
        plan=ip.map_appdata(body['plan'],found,persona=body['persona'],serial=body['serial'],partuuid=body['partuuid']) if body['action']=='map_appdata' else body['plan']
    try:errors=ip.validate(plan,found)
    except (TypeError,KeyError):
        raise ip.PlanError('invalid plan field types; review storage, environment and application choices') from None
    candidates=[]
    for drive in found['drives']:
        for volume in drive['volumes']:
            identity=ip._partuuid(volume['partuuid'])
            if (volume['name'].startswith('APPDATA_') and volume['fstype']=='ext4'
                    and identity is not None and found.get('partuuid_counts',{}).get(identity)==1):
                candidates.append({'persona':volume['name'][8:].lower(),'serial':drive['serial'],
                                   'partuuid':identity,'volume':volume['name'],'model':drive['model']})
    result={'ok':True,'valid':not errors,'executed':False,'plan':plan,'errors':errors,'appdata_candidates':candidates}
    if body['action']=='compile':
        result['stages']=ip.compile_plan(plan,found)
    return result


def discover_current():
    """Fresh read-only listing; existing enrollment and boot exclusion remain authoritative."""
    import subprocess
    import drive_admin
    import physical_device_safety as pds
    try:
        boot=pds.get_boot_device_serial(pds.Runner())
        if not isinstance(boot,str) or not boot.strip():
            raise ip.PlanError('could not establish the running boot drive identity; no plan is offered')
        proc=subprocess.run(ip.lsblk_argv(),capture_output=True,text=True,timeout=30)
        if proc.returncode:raise ip.PlanError('drive discovery command failed; no plan is offered')
        return ip.discover(proc.stdout,allowed_serials=drive_admin.allowed_target_serials(),
                           boot_serial=boot)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise ip.PlanError('drive discovery unavailable; no plan is offered') from exc


def render():
    return br'''<!doctype html><html><head><meta charset="utf-8"><title>Installer plan</title>
<style>body{font-family:system-ui;max-width:1000px;margin:2rem auto;padding:1rem;background:#10151e;color:#eee}textarea{box-sizing:border-box;width:100%;min-height:26rem;font-family:monospace}button{padding:.7rem;margin:.4rem 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#8ac8ff}.baseline-nav{display:flex;flex-wrap:wrap;gap:.5rem;margin-bottom:1.5rem}</style></head><body>
<h1>Installer plan</h1>
<p>Discover enrolled drives and fill in editable storage, Ubuntu and application choices. Validate again after editing: each request checks the drives present now.</p>
<p><strong>No stages are executed here.</strong> Preview and export do not format drives, mount volumes, install an OS or launch applications. Running the stages as a recoverable job is still unfinished.</p>
<button type="button" onclick="run('autofill')">Discover and autofill</button>
<p>Autofill replaces the editor contents. Export an existing plan before starting over.</p>
<label for="plan">Build choices (JSON)</label><textarea id="plan" spellcheck="false" aria-describedby="choices"></textarea>
<p id="choices">Change environment.name and variant (desktop/server), applications.apps, run_as and cache/generation_root/data paths. Drives are chosen by serial; retained volumes by PARTUUID. Ambiguous drives stay unset. Missing volumes need an explicit repair decision; this page never erases data to fill a gap. Only Ubuntu 24.04 provisioning is supported here.</p>
<h2>Map an existing AppData volume</h2>
<p>Select a dedicated ext4 APPDATA partition on an enrolled drive. This can preserve the six-volume Baseline drive without repartitioning. A user or cache directory is not an AppData volume. Missing target volumes must be provisioned separately; this page does not create them.</p>
<label for="target">Discovered AppData targets</label><select id="target" onchange="chooseTarget()"><option value="">Discover first</option></select>
<label for="persona">Persona</label><input id="persona" value="admin" maxlength="8">
<label for="serial">Target drive serial</label><input id="serial">
<label for="partuuid">Target PARTUUID</label><input id="partuuid">
<button type="button" onclick="run('map_appdata')">Apply mapping to plan</button>
<button type="button" onclick="run('validate')">Validate current choices</button>
<button type="button" onclick="run('compile')">Preview stage parameters</button>
<button type="button" id="export" disabled onclick="download()">Export validated plan</button>
<p id="status" role="status" aria-live="polite"></p><pre id="result"></pre>
<p>Application cache, disposable generations and private data paths must be separate. Guest path defaults are not proof of physical volume routing. Private data must be retained across an OS rebuild; configuration recipes are separate from private backups.</p>
<p>Use <a href="/drive-admin">Drive Administration</a> for deliberate enrollment and existing gated drive actions, <a href="/vms">Virtual machines</a> for current Ubuntu creation, and <a href="/recipes">Environment recipes</a> for configuration templates. Full installer/firstboot execution remains unverified.</p>
<script>
let epoch=0,validated=null,candidates=[];
const editor=document.getElementById('plan'),status=document.getElementById('status'),output=document.getElementById('result'),exportButton=document.getElementById('export');
function invalidate(){epoch++;validated=null;exportButton.disabled=true;output.textContent='';status.textContent='Choices changed; validate against current drives.';}
editor.addEventListener('input',invalidate);
async function run(action){
 const version=++epoch;validated=null;exportButton.disabled=true;output.textContent='';
 try{
  const body={action};if(action!=='autofill'){if(new TextEncoder().encode(editor.value).length>65536)throw Error('Plan exceeds 64 KiB');body.plan=JSON.parse(editor.value);}
  if(action==='map_appdata'){body.persona=document.getElementById('persona').value;body.serial=document.getElementById('serial').value;body.partuuid=document.getElementById('partuuid').value;}
  status.textContent='Checking current drives...';
  const response=await fetch('/install-plan/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result=await response.json();if(version!==epoch)return;
  if(!response.ok||!result.ok)throw Error((result.errors||[result.message||'Plan refused']).join('\n'));
  candidates=result.appdata_candidates||[];const target=document.getElementById('target');target.replaceChildren();
  const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent=candidates.length?'Choose an existing AppData target':'No unique ready AppData volumes found';target.append(placeholder);
  for(const [index,item] of candidates.entries()){const option=document.createElement('option');option.value=String(index);option.textContent=item.persona+' - '+item.volume+' on '+item.model+' ('+item.serial+')';target.append(option);}
  if(action==='autofill'||action==='map_appdata')editor.value=JSON.stringify(result.plan,null,2);
  output.textContent=JSON.stringify(result.stages||{notes:result.plan.notes||[],errors:result.errors},null,2);
  status.textContent=result.valid?'Valid against current discovery. Nothing executed.':result.errors.join('\n');
  if(result.valid){validated=JSON.stringify(result.plan,null,2)+'\n';exportButton.disabled=false;}
 }catch(error){if(version===epoch)status.textContent=error.message;}
}
function chooseTarget(){const value=document.getElementById('target').value;if(value==='')return;const item=candidates[Number(value)];if(!item)return;for(const field of ['persona','serial','partuuid'])document.getElementById(field).value=item[field];}
function download(){if(!validated)return;const url=URL.createObjectURL(new Blob([validated],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='baseline-install-plan.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
</script></body></html>'''
