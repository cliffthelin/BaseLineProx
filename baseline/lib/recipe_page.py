"""Read-only recipe transformations. No deployment state or raw profile export."""
import hashlib
import json
import environment_recipes as er


def perform(body):
    if not isinstance(body,dict):raise er.RecipeError('recipe action must be an object')
    action=body.get('action')
    keys={'action','document','app_document'} if action=='compose' else {'action','document'}
    if set(body)-keys or not {'action','document'}<=set(body):
        raise er.RecipeError('unsupported recipe action fields')
    excluded_count=None
    if action=='capture_vscode':
        import vscode_capture
        preview=vscode_capture.capture(body['document'])
        document=preview['document'];serialized=vscode_capture.export(document)
        excluded_count=preview['excluded_count']
    elif action=='validate':
        document=er.load(body['document']);serialized=er.export(document)
    elif action=='verify':
        document=er.verify_stack(er.read_document(body['document']))
        serialized=json.dumps(document,sort_keys=True,separators=(',',':'))+'\n'
    elif action=='compose':
        app_text=body.get('app_document','')
        apps=[] if app_text=='' else [er.load(app_text)]
        document=er.compose(er.load(body['document']),apps)
        serialized=json.dumps(document,sort_keys=True,separators=(',',':'))+'\n'
    else:raise er.RecipeError('unsupported recipe action')
    return {'ok':True,'document':document,'export_json':serialized,
            'digest':hashlib.sha256(serialized.encode('ascii')).hexdigest(),
            'runtime_applied':False,'sources_verified':False,'excluded_count':excluded_count}


def render():
    import structured_controls
    import configuration_draft_ui
    page = b'''<!doctype html><html><head><meta charset="utf-8"><title>Environment recipes</title>
<style>body{font-family:system-ui;max-width:960px;margin:2rem auto;padding:1rem;background:#10151e;color:#eee}textarea{display:block;width:100%;height:13rem;margin:1rem 0}button{padding:.6rem;margin:.4rem}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style></head><body>
<h1>Environment recipes</h1>
<h2>Inspect installed application</h2>
<p>Read installed Debian package metadata in a running managed Ubuntu/Proxmox VM. Reports version, dependencies and configuration locations only. No profile or secrets are copied. Containers and other media are not supported yet. Inspection is not a deployable recipe or test-install proof.</p>
<label for="capture_vm">Managed VM name</label><input id="capture_vm">
<label for="capture_package">Installed Debian package name</label><input id="capture_package">
<button onclick="inspectApp()">Inspect installed application</button>
<p id="capture_status" role="status" aria-live="polite"></p><pre id="capture_result"></pre>
<h2>Validate and compose recipes</h2>
<p>Validate configuration-only templates or compose an OS recipe with an application recipe.</p>
<p><strong>Recipes are not deployed. Sources have not been verified.</strong> This page does not install a VM, apply overlays or capture a user profile.</p>
<p>Initial contract: Ubuntu 24.04 amd64 desktop/server and Chromium. OS locale and symbolic environment-console homepage only. Other settings and private runtime fields are refused. State declarations do not establish complete retention coverage.</p>
<p id="draft-status" role="status" aria-live="polite"></p><button type="button" id="draft-retry" hidden>Retry loading draft</button>
<fieldset id="draft-fields" disabled style="border:0;padding:0;margin:0"><label for="recipe-template">Recipe template</label><select id="recipe-template" onchange="chooseRecipe()"><option value="ubuntu-desktop">Ubuntu Desktop 24.04</option><option value="ubuntu-server">Ubuntu Server 24.04</option><option value="chromium">Chromium</option></select>
<label for="document">Recipe choices (or import a saved recipe)</label>
<input type="file" id="file" accept=".json,application/json" aria-label="Load recipe JSON file">
<details><summary>Advanced JSON override</summary><textarea id="document" spellcheck="false" disabled></textarea></details>
<label for="include-app"><input type="checkbox" id="include-app" onchange="chooseApp()"> Include Chromium when composing</label>
<label for="app_document">Application recipe choices (optional)</label>
<input type="file" id="appfile" accept=".json,application/json" aria-label="Load app recipe JSON file">
<details><summary>Advanced JSON override</summary><textarea id="app_document" spellcheck="false" disabled></textarea></details>
<button onclick="run('capture_vscode')">Preview VS Code settings</button>
<p>VS Code preview accepts a selected settings.json (JSON with comments). Only font size, tab size, spaces, word wrap and auto-save are included. Unknown settings are excluded; extensions, snippets, keybindings and Spotify capture remain unimplemented. Output is a settings artifact, not an installable recipe.</p>
<button onclick="run('validate')">Validate recipe</button><button onclick="run('compose')">Compose stack</button><button onclick="run('verify')">Verify stack</button>
<button id="download" disabled onclick="download()">Export validated JSON</button>
<p id="status" role="status" aria-live="polite"></p><pre id="result"></pre>
</fieldset>
<script>
const recipeOptions={'platform.os':['ubuntu'],'platform.release':['24.04'],'platform.arch':['amd64'],
 'configuration.homepage_role':['environment_console'],retention:['retained']};
const recipeEditor=new BaselineStructuredEditor(document.getElementById('document'),recipeOptions);
const appEditor=new BaselineStructuredEditor(document.getElementById('app_document'),recipeOptions);
function template(id){const app=id==='chromium';return {format:'baseline.recipe/v1',kind:app?'app':'os',id,
 platform:{os:'ubuntu',release:'24.04',arch:'amd64'},source:{sha256:''},
 configuration:app?{homepage_role:'environment_console'}:{locale:'en_US.UTF-8'},
 state:[{path:app?'~/.config/chromium':'/home',role:app?'app_private':'documents',retention:'retained'}]};}
function chooseRecipe(){recipeEditor.set(template(document.getElementById('recipe-template').value));clear();}
function chooseApp(){if(document.getElementById('include-app').checked)appEditor.set(template('chromium'));
 else {appEditor.set(null);document.getElementById('app_document').value='';}clear();}
async function inspectApp(){
 const status=document.getElementById('capture_status'),output=document.getElementById('capture_result');output.textContent='';
 try{const response=await fetch('/vms/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'inspect_app',name:document.getElementById('capture_vm').value,package:document.getElementById('capture_package').value,request_id:'inspect-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)})});
 const submitted=await response.json();if(!response.ok)throw Error(submitted.message||'Inspection refused');
 status.textContent='Inspection job '+submitted.job_id+'. You can reconnect through Workload jobs.';
 for(;;){await new Promise(resolve=>setTimeout(resolve,1000));const response=await fetch('/workloads/job?job_id='+encodeURIComponent(submitted.job_id));const job=await response.json();
 if(!response.ok)throw Error('Job inspection unavailable; open Workload jobs');
 if(['queued','running'].includes(job.state))continue;
 if(job.state==='interrupted')throw Error('Inspection interrupted. Open Workload jobs; no success inferred.');
 const completed=await fetch('/workloads/result',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:submitted.job_id})});const result=await completed.json();
 if(!completed.ok||!result.ok)throw Error(result.message||'Inspection failed');
 output.textContent=JSON.stringify(result.capture_report,null,2);status.textContent=result.message;break;}
 }catch(error){status.textContent=error.message;}
}
let validated=null;
function clear(){validated=null;document.getElementById('download').disabled=true;document.getElementById('result').textContent='';}
for(const id of ['document','app_document'])document.getElementById(id).addEventListener('input',clear);
for(const [id,target] of [['file','document'],['appfile','app_document']])document.getElementById(id).addEventListener('change',async event=>{
 clear();const file=event.target.files[0];if(!file)return;
 if(file.size>65536){document.getElementById('status').textContent='Refused: file exceeds 64 KiB';return;}
 const text=await file.text();try{const targetEditor=target==='document'?recipeEditor:appEditor;targetEditor.set(JSON.parse(text));targetEditor.sync();}
 catch(error){document.getElementById('status').textContent='Use the advanced override for JSON with comments; file could not be parsed: '+error.message;}
});
async function run(action){
 clear();const snapshot=[document.getElementById('document').value,document.getElementById('app_document').value];
 const body={action,document:snapshot[0]};if(action==='compose')body.app_document=snapshot[1];
 document.getElementById('status').textContent='Checking configuration...';
 try{const response=await fetch('/recipes/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const result=await response.json();if(!response.ok||!result.ok)throw Error(result.message||'Recipe check refused');
 if(snapshot[0]!==document.getElementById('document').value||snapshot[1]!==document.getElementById('app_document').value)throw Error('Input changed; validate again');
 validated=result.export_json;document.getElementById('download').disabled=false;
 document.getElementById('result').textContent=JSON.stringify(result.document,null,2);
 document.getElementById('status').textContent='Configuration validated. Not deployed; sources unverified. '+(result.excluded_count===null?'':result.excluded_count+' unsupported setting(s) excluded. ')+'SHA256 '+result.digest;
 }catch(error){clear();document.getElementById('status').textContent=error.message;}
}
function download(){if(validated===null)return;const url=URL.createObjectURL(new Blob([validated],{type:'application/json'}));
 const link=document.createElement('a');link.href=url;link.download='baseline-recipe.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
chooseRecipe();
baselineDraft({endpoint:'/recipes/draft',read:()=>({document:JSON.parse(document.getElementById('document').value),app_document:document.getElementById('app_document').value?JSON.parse(document.getElementById('app_document').value):null}),
 restore:value=>{recipeEditor.set(value.document);appEditor.set(value.app_document);if(!value.app_document)document.getElementById('app_document').value='';
  document.getElementById('include-app').checked=!!value.app_document;
  if(['ubuntu-desktop','ubuntu-server','chromium'].includes(value.document.id))document.getElementById('recipe-template').value=value.document.id;clear();},
 inputs:[document.getElementById('document'),document.getElementById('app_document'),document.getElementById('recipe-template'),document.getElementById('include-app')]});
</script></body></html>'''
    return page.replace(b'<script>\nconst recipeOptions', (structured_controls.script()+configuration_draft_ui.script()).encode()+b'<script>\nconst recipeOptions')
