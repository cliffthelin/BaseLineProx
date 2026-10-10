"""Installer draft editor and confirmed existing-installation update controls."""
import json
import install_plan as ip


def perform(body, *, discovery_provider):
    if not isinstance(body,dict) or body.get('action') not in ('autofill','single-drive','validate','compile','map_appdata'):
        raise ip.PlanError('unsupported installer plan action')
    required={'action'} if body['action']=='autofill' else {'action','plan'}
    if body['action']=='single-drive':required={'action','serial'}
    if body['action']=='map_appdata':required={'action','plan','persona','serial','partuuid'}
    if set(body)!=required:raise ip.PlanError('unsupported or missing installer plan fields')
    if 'plan' in body:
        try:size=len(json.dumps(body['plan'],ensure_ascii=False,allow_nan=False).encode('utf-8'))
        except (ValueError,TypeError,RecursionError):raise ip.PlanError('plan must contain JSON values') from None
        if size>65536:raise ip.PlanError('plan exceeds 64 KiB')
    found=discovery_provider()
    if body['action']=='autofill':
        plan=ip.autofill(found)
    elif body['action']=='single-drive':
        plan=ip.autofill_single_drive(found,body['serial'])
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


def catalog_entries(root=None, *, catalog_directory=None):
    import application_bundle as ab
    names={'vscode':'Visual Studio Code','spotify':'Spotify','chrome':'Google Chrome','chatgpt':'ChatGPT','claude':'Claude'}
    definitions=[]
    if root is not None:definitions.extend(ab.load_application_definitions(root))
    if catalog_directory is not None:definitions.extend(ab.load_application_catalog(catalog_directory))
    for definition in definitions:names[definition['id']]=definition['name']
    return [{'id':app,'name':names.get(app,app),'icon':'/installer-icons/'+app+'.png',
             'package':ab.PACKAGES[app],'executable':ab.EXECUTABLES[app],
             'configuration':{'scale':1} if app in ('spotify','chrome','chatgpt','claude') else {}}
            for app in ab.APPS]



_WORKSPACE_HTML = r"""<div class="desktop-wallpaper" aria-hidden="true"></div>
<section class="installer-workspace" aria-labelledby="workspace-title">
<header class="workspace-header"><div><span class="eyebrow">BASELINE / INSTALLER</span><h1 id="workspace-title">Your installation workspace</h1><p>Drag a drive into the target. Add operating systems and applications as desktop shortcuts.</p></div><button id="start-installation-update" class="primary" type="button" disabled onclick="startWorkspaceUpdate()">Update selected drive</button></header>
<div id="workspace-message" role="status" aria-live="polite">Discovering connected drives and available recipes...</div>
<div class="workspace-columns">
<section class="workspace-pane icon-folder"><h2>Connected drives</h2><div id="workspace-drives"></div><p class="muted">Identity is checked by serial. Protected drives cannot be selected.</p></section>
<section class="workspace-pane icon-folder"><h2>Operating systems <span id="os-count" class="count"></span></h2><div id="os-shortcuts" class="shortcut-grid"></div><p class="muted">Right-click a shortcut for details and configuration.</p></section>
<section class="workspace-pane icon-folder"><div class="pane-title"><h2>Applications <span id="application-count" class="count"></span></h2><button type="button" onclick="document.getElementById('add-application').showModal()">Add application</button></div><div id="application-shortcuts" class="shortcut-grid"></div><p class="muted">The catalog can grow. Drag shortcuts to add them; right-click to configure.</p></section>
</div>
<div class="workspace-selection">
<section id="installation-target" class="drop-target" tabindex="0" aria-label="Installation drive drop target"><span class="eyebrow">INSTALLATION DRIVE</span><div id="target-drive-content">Drop a connected drive here</div></section>
<section id="environment-target" class="drop-target" tabindex="0" aria-label="Operating system drop target"><span class="eyebrow">ENVIRONMENT CHOICES</span><div id="target-environment-content">Drop an operating system here</div></section>
<section id="application-target" class="drop-target" tabindex="0" aria-label="Application drop target"><span class="eyebrow">APPLICATION CHOICES</span><div id="selected-application-shortcuts" class="shortcut-grid compact"></div></section>
</div>
<div class="workspace-progress"><ol><li data-stage="discovery">Verify target</li><li data-stage="source">Prepare inputs</li><li data-stage="authorization">Native authorization</li><li data-stage="deployment">Deploy</li><li data-stage="boot">Boot and verify</li></ol><p id="update-status" role="status" aria-live="polite">No drive changes have started.</p></div>
<p class="muted">Environment and application choices are saved configuration. The current existing-drive update refreshes Baseline and boot files; it does not claim those workloads have been installed.</p>
</section>
<dialog id="shortcut-details"><form id="shortcut-settings-form"><div class="modal-title"><img id="shortcut-detail-icon" alt=""><div><span class="eyebrow" id="shortcut-detail-kind"></span><h2 id="shortcut-detail-name"></h2></div><button type="button" aria-label="Close shortcut details" onclick="document.getElementById('shortcut-details').close()">&#215;</button></div><p id="shortcut-detail-description"></p><div id="shortcut-settings-fields"></div><p id="shortcut-settings-status" role="status"></p><div class="dialog-actions"><button type="button" onclick="document.getElementById('shortcut-details').close()">Cancel</button><button type="submit" class="primary">Save configuration</button></div></form></dialog>
<dialog id="add-application"><form onsubmit="addWorkspaceApplication(event)"><h2>Add an application</h2><p>Provide the exact publisher .deb URL and its published SHA256. Baseline verifies the downloaded bytes and Debian package identity before using it.</p><label>Name<input name="name" required maxlength="80"></label><label>Application ID<input name="id" required pattern="[a-z][a-z0-9-]{1,47}"></label><label>Native package<input name="package" required></label><label>Executable inside package<input name="executable" placeholder="usr/bin/application" required></label><label>Exact HTTPS package URL<input name="source_url" type="url" placeholder="https://publisher.example/packages/application_1.0_amd64.deb" required></label><label>Published SHA256<input name="sha256" inputmode="text" pattern="[a-f0-9]{64}" minlength="64" maxlength="64" required></label><p id="catalog-save-status" role="status"></p><div class="dialog-actions"><button type="button" onclick="document.getElementById('add-application').close()">Cancel</button><button class="primary" type="submit">Add to catalog</button></div></form></dialog>
<details id="advanced-installer"><summary>Advanced configuration and installation details</summary>""".encode()
_WORKSPACE_CSS = r"""<style>
body{max-width:none;width:auto;margin:0;padding:20px;box-sizing:border-box;background:#0b1119;color:#e8edf4}*{box-sizing:border-box}.baseline-nav{margin-bottom:24px}.workspace-header{display:flex;align-items:center;justify-content:space-between;gap:24px}.workspace-header h1{font-size:clamp(24px,2.4vw,38px);margin:8px 0}.workspace-header p{color:#9caec3;margin:0}.eyebrow{font-size:11px;font-weight:700;letter-spacing:.14em;color:#8fa5bd}.primary{background:#69dfc0;color:#06231c;border:0;font-weight:700;border-radius:10px;padding:13px 20px}.primary:disabled{opacity:.45;cursor:not-allowed}button{cursor:pointer}#workspace-message{margin:20px 0;color:#abc0d8}.workspace-columns{display:grid;grid-template-columns:minmax(230px,.85fr) minmax(250px,1fr) minmax(320px,1.7fr);gap:16px}.workspace-pane,.workspace-progress{background:#141d2a;border:1px solid #273447;border-radius:14px;padding:20px}.workspace-pane h2{font-size:16px;margin:0 0 20px}.pane-title{display:flex;align-items:center;justify-content:space-between;gap:10px}.pane-title button{background:#233349;color:#dbe8f8;border:1px solid #3a4c66;border-radius:8px;padding:7px 10px;margin:0 0 20px}.count{font-size:11px;background:#243349;border-radius:20px;padding:3px 8px;margin-left:6px}.drive-card-tile{display:block;text-align:left;width:100%;margin:10px 0;padding:15px;background:#1c2a3d;border:1px solid #3c506c;border-radius:10px;color:inherit;overflow-wrap:anywhere}.drive-card-tile strong{display:block;font-size:15px;margin-bottom:8px}.drive-card-tile small{display:block;color:#97abc3;font-size:11px;line-height:1.6}.drive-card-tile[aria-disabled=true]{opacity:.6;cursor:default;background:#19212d}.shortcut-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(86px,1fr));gap:10px;align-content:start}.desktop-shortcut{display:flex;flex-direction:column;align-items:center;justify-content:flex-start;gap:9px;background:transparent;color:#e3eaf5;border:1px solid transparent;border-radius:10px;padding:13px 5px;margin:0;min-height:105px;text-align:center;user-select:none}.desktop-shortcut:hover,.desktop-shortcut:focus-visible{background:#24364c;border-color:#54718f;outline:0}.desktop-shortcut img{height:48px;width:48px;object-fit:contain;pointer-events:none}.desktop-shortcut span{font-size:12px;line-height:1.3;max-width:110px;pointer-events:none}.shortcut-grid.compact .desktop-shortcut{background:#1d2c3e}.workspace-selection{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:20px 0}.drop-target{min-height:125px;border:2px dashed #3a516b;background:#101c2b;border-radius:14px;padding:20px;overflow-wrap:anywhere}.drop-target .eyebrow{display:block;margin-bottom:14px}.drop-target.drag-over{border-color:#69dfc0;background:#16382f}.drop-target img{height:40px;width:40px;object-fit:contain}.target-summary{display:flex;align-items:center;gap:14px}.target-summary strong{display:block;font-size:15px;margin-bottom:5px}.target-summary small{color:#9aaec5}.muted{font-size:12px;line-height:1.6;color:#8fa5bd}.workspace-progress ol{display:flex;flex-wrap:wrap;gap:16px;list-style:none;padding:0;margin:0 0 16px;counter-reset:phase}.workspace-progress li{counter-increment:phase;color:#8295ad;font-size:13px}.workspace-progress li:before{content:counter(phase);display:inline-grid;place-items:center;width:24px;height:24px;margin-right:7px;border:1px solid #3a4d67;border-radius:50%}.workspace-progress li.active{color:#69dfc0}.workspace-progress li.done:before{background:#234b3f;border-color:#69dfc0;color:#69dfc0}.workspace-progress p{margin:0;font-size:13px;line-height:1.7}#advanced-installer{margin-top:24px;padding:18px;border:1px solid #2c3e55;border-radius:12px}#advanced-installer>summary{cursor:pointer;color:#a9bdd5}dialog{background:#172231;color:#e5edf8;border:1px solid #425571;border-radius:16px;max-width:min(620px,94vw);padding:26px}dialog::backdrop{background:#03080ed4}dialog label{display:block;margin:14px 0;font-size:13px;color:#b8c9dd}dialog input,dialog select,dialog textarea{display:block;width:100%;margin-top:8px;background:#0e1724;color:#edf4fc;border:1px solid #425572;border-radius:7px;padding:10px}dialog textarea{min-height:80px}dialog button{border-radius:7px}dialog h2{margin:0 0 10px}dialog p{font-size:13px;line-height:1.6;color:#acbed3}.modal-title{display:flex;gap:16px;align-items:center}.modal-title img{width:54px;height:54px;object-fit:contain}.modal-title>button{margin-left:auto;background:transparent;border:0;color:#cbd9eb;font-size:26px}.dialog-actions{display:flex;justify-content:flex-end;gap:12px;margin-top:24px}#shortcut-settings-form{min-width:min(440px,80vw)}
@media(min-width:1600px){.shortcut-grid{grid-template-columns:repeat(auto-fill,minmax(100px,1fr))}.workspace-pane{min-height:290px}}@media(max-width:1050px){.workspace-columns{grid-template-columns:repeat(2,minmax(0,1fr))}.workspace-pane:last-child{grid-column:1/-1}}@media(max-width:680px){body{padding:12px}.workspace-header{align-items:flex-start;flex-direction:column}.workspace-header .primary{width:100%}.workspace-columns,.workspace-selection{grid-template-columns:1fr}.workspace-pane:last-child{grid-column:auto}.workspace-pane{padding:16px}}

/* Wallpaper and grouped shortcuts share the full browser workspace. */
body{background:#101c35;min-height:100vh;isolation:isolate}
.desktop-wallpaper{position:fixed;inset:0;z-index:-1;pointer-events:none;background:radial-gradient(ellipse at 75% 18%,#efa99b66 0,transparent 42%),radial-gradient(ellipse at 12% 58%,#6189bd66 0,transparent 55%),linear-gradient(155deg,#253e68 0%,#293454 45%,#161f37 100%)}
.desktop-wallpaper::after{content:"";position:absolute;inset:35% 0 0;background:linear-gradient(145deg,#29466099,#131e3799);clip-path:polygon(0 55%,18% 15%,35% 50%,59% 0,79% 42%,100% 17%,100% 100%,0 100%)}
.workspace-pane.icon-folder{background:#14233b99;border:1px solid #ffffff26;border-radius:28px;backdrop-filter:blur(22px);box-shadow:0 16px 48px #050d2426;padding:24px}
.workspace-header{padding:12px 4px 24px}.workspace-header h1{letter-spacing:-.035em}.eyebrow{letter-spacing:.16em}
.shortcut-grid{gap:18px 12px;align-content:start}.desktop-shortcut{border-radius:20px;background:transparent;border:1px solid transparent;transition:background .15s}
.desktop-shortcut:hover,.desktop-shortcut:focus-visible{background:#ffffff16;border-color:#ffffff35}
.desktop-shortcut img{filter:drop-shadow(0 5px 8px #0004)}
.drop-target,.workspace-progress{background:#122039aa;backdrop-filter:blur(18px);border-radius:24px}
dialog{background:#17273bf5;border:1px solid #ffffff35;border-radius:24px;box-shadow:0 24px 90px #0008}dialog::backdrop{background:#07102488;backdrop-filter:blur(8px)}
@media(max-width:680px){body{padding:12px}.workspace-pane.icon-folder{padding:18px;border-radius:24px}.shortcut-grid{grid-template-columns:repeat(auto-fill,minmax(86px,1fr))}}
@media(prefers-reduced-motion:reduce){.desktop-shortcut{transition:none}.desktop-shortcut:hover,.desktop-shortcut:focus-visible{transform:none}}
</style>""".encode()
_WORKSPACE_JS = r"""
let workspaceCatalog=null,workspaceTarget=null,workspaceBusy=false;
function installerPhase(stage){const stages=['discovery','source','authorization','deployment','boot'];for(const node of document.querySelectorAll('[data-stage]')){const index=stages.indexOf(node.dataset.stage),current=stages.indexOf(stage);node.classList.toggle('active',index===current);node.classList.toggle('done',index<current);}}
function shortcutImage(src){const image=document.createElement('img');image.src=src;image.alt='';image.draggable=false;image.onerror=()=>{image.onerror=null;image.src='/installer-icons/application.svg';};return image;}
function createShortcut(item,kind,selected=false){const button=document.createElement('button');button.type='button';button.className='desktop-shortcut';button.draggable=true;button.title=item.name+' — drag to add; right-click to configure';if(kind==='app')button.dataset.appId=item.id;else button.dataset.osVariant=item.variant;button.append(shortcutImage(item.icon));const label=document.createElement('span');label.textContent=item.name;button.append(label);button.addEventListener('dragstart',event=>event.dataTransfer.setData('application/x-baseline-shortcut',JSON.stringify({kind,id:item.id,variant:item.variant})));button.addEventListener('contextmenu',event=>{event.preventDefault();showShortcutDetails(item,kind);});button.addEventListener('keydown',event=>{if(event.key==='ContextMenu'||(event.shiftKey&&event.key==='F10')){event.preventDefault();showShortcutDetails(item,kind);}});button.onclick=()=>selected?showShortcutDetails(item,kind):addShortcutChoice(item,kind);return button;}
function currentWorkspacePlan(){try{return JSON.parse(editor.value);}catch(error){if(!workspaceCatalog)throw Error('Current discovery is unavailable');return structuredClone(workspaceCatalog.plan);}}
async function saveWorkspacePlan(plan){choiceEditor.set(plan);editor.dispatchEvent(new Event('input',{bubbles:true}));renderWorkspaceChoices();await installerDraft.flush();document.getElementById('workspace-message').textContent='Configuration saved. Target and source checks run before deployment.';}
async function addShortcutChoice(item,kind){try{const plan=currentWorkspacePlan();if(kind==='os'){plan.environment.os=item.id;plan.environment.variant=item.variant;if(item.environmentName)plan.environment.name=item.environmentName;}else if(!plan.applications.apps.includes(item.id)){plan.applications.apps.push(item.id);}await saveWorkspacePlan(plan);return true;}catch(error){document.getElementById('workspace-message').textContent='Installer choice was not saved: '+error.message;return false;}}
function renderWorkspaceChoices(){if(!workspaceCatalog)return;const plan=currentWorkspacePlan(),environment=document.getElementById('target-environment-content'),apps=document.getElementById('selected-application-shortcuts');environment.replaceChildren();const chosenOS={id:plan.environment.os,variant:plan.environment.variant,name:'Ubuntu 24.04 '+plan.environment.variant,icon:'/installer-icons/'+plan.environment.os+'.svg'};environment.append(createShortcut(chosenOS,'os',true));apps.replaceChildren();for(const app of workspaceCatalog.application_entries.filter(item=>plan.applications.apps.includes(item.id)))apps.append(createShortcut(app,'app',true));}
function chooseWorkspaceDrive(drive){if(workspaceBusy||workspaceCatalog.protected_serials.includes(drive.serial))return;workspaceTarget=drive;document.getElementById('update-serial').value=drive.serial;const box=document.getElementById('target-drive-content');box.replaceChildren();const strong=document.createElement('strong');strong.textContent=drive.model||drive.serial;const serial=document.createElement('small');serial.textContent=drive.serial+' · '+(Number(drive.size_bytes)/1024**3).toFixed(1)+' GiB';box.append(strong,document.createElement('br'),serial);document.getElementById('start-installation-update').disabled=false;document.getElementById('workspace-message').textContent='Selected '+drive.serial+'. Other drives are preserved.';}
function installWorkspaceDrop(id,kind){const node=document.getElementById(id);node.addEventListener('dragover',event=>{event.preventDefault();node.classList.add('drag-over');});node.addEventListener('dragleave',()=>node.classList.remove('drag-over'));node.addEventListener('drop',event=>{event.preventDefault();node.classList.remove('drag-over');try{const item=JSON.parse(event.dataTransfer.getData('application/x-baseline-shortcut'));if(item.kind!==kind)throw Error('Drop a '+kind+' shortcut here');if(kind==='drive'){const drive=workspaceCatalog.drives.find(d=>d.serial===item.id);if(!drive)throw Error('Drive is no longer present');chooseWorkspaceDrive(drive);}else{const record=kind==='app'?workspaceCatalog.application_entries.find(a=>a.id===item.id):{id:item.id,variant:item.variant};if(!record)throw Error('Shortcut is no longer in the catalog');addShortcutChoice(record,kind);}}catch(error){document.getElementById('workspace-message').textContent=error.message;}});}
function detailField(name,label,value,type='text'){const wrapper=document.createElement('label');wrapper.textContent=label;const input=document.createElement('input');input.name=name;input.type=type;input.value=value??'';wrapper.append(input);document.getElementById('shortcut-settings-fields').append(wrapper);return input;}
function showShortcutDetails(item,kind){const modal=document.getElementById('shortcut-details'),fields=document.getElementById('shortcut-settings-fields'),form=document.getElementById('shortcut-settings-form');fields.replaceChildren();document.getElementById('shortcut-detail-name').textContent=item.name;document.getElementById('shortcut-detail-kind').textContent=kind==='app'?'APPLICATION CONFIGURATION':'OPERATING SYSTEM CONFIGURATION';document.getElementById('shortcut-detail-icon').src=item.icon;document.getElementById('shortcut-settings-status').textContent='';const plan=currentWorkspacePlan();if(kind==='os'){document.getElementById('shortcut-detail-description').textContent='Ubuntu 24.04 '+item.variant+'. OS changes use disposable storage; user and application data must remain in retained volumes.';detailField('name','Environment name',plan.environment.name);detailField('variant','Variant',item.variant).readOnly=true;form.onsubmit=async event=>{event.preventDefault();try{plan.environment={os:item.id,variant:item.variant,name:new FormData(form).get('name')};await saveWorkspacePlan(plan);modal.close();}catch(error){document.getElementById('shortcut-settings-status').textContent=error.message;}};}else{document.getElementById('shortcut-detail-description').textContent='Native package: '+item.package+'. Configuration is saved separately from private account/profile data; registration is not installation or runtime verification.';const config=(plan.applications.configurations||{})[item.id]||{};if(item.id==='vscode'){detailField('font','Editor font size',config['editor.fontSize']||14,'number');detailField('theme','Color theme',config['workbench.colorTheme']||'Default Dark Modern');}else if(['spotify','chrome','chatgpt','claude'].includes(item.id)){const scale=detailField('scale','Display scale',config.scale||1,'number');scale.step='.05';scale.min='.75';scale.max='2';if(item.id==='chrome')detailField('homepage','Homepage',config.homepage||'https://www.proxmox.com/','url');}else{detailField('arguments','Launch arguments (JSON array)',JSON.stringify(config.arguments||[]));}form.onsubmit=async event=>{event.preventDefault();try{const values=new FormData(form);let configuration=item.id==='vscode'?{'editor.fontSize':Number(values.get('font')),'workbench.colorTheme':values.get('theme')}:values.has('scale')?{scale:Number(values.get('scale'))}:{arguments:JSON.parse(values.get('arguments'))};if(values.has('homepage'))configuration.homepage=values.get('homepage');const result=await updatePost('/install-plan/app-config',{app:item.id,configuration});plan.applications.configurations=plan.applications.configurations||{};plan.applications.configurations[item.id]=result.configuration;await saveWorkspacePlan(plan);modal.close();}catch(error){document.getElementById('shortcut-settings-status').textContent=error.message;}};}modal.showModal();}
async function addWorkspaceApplication(event){event.preventDefault();const form=event.target,status=document.getElementById('catalog-save-status');try{const definition=Object.fromEntries(new FormData(form));await updatePost('/install-plan/catalog',{definition});document.getElementById('add-application').close();await loadWorkspaceCatalog();if(installerDisplay)renderInstallerDisplay();status.textContent='';}catch(error){status.textContent=error.message;}}
async function loadWorkspaceCatalog(){const response=await fetch('/install-plan/discovery',{credentials:'same-origin',cache:'no-store'});const found=await response.json();if(!response.ok)throw Error(found.message||'Current discovery unavailable');workspaceCatalog=found;await installerDraft.loaded;if(!editor.value.trim())choiceEditor.set(found.plan);const drives=document.getElementById('workspace-drives');drives.replaceChildren();for(const drive of found.drives){const protectedDrive=found.protected_serials.includes(drive.serial),button=document.createElement('button');button.type='button';button.className='drive-card-tile';button.dataset.driveSerial=drive.serial;button.draggable=!protectedDrive;button.setAttribute('aria-disabled',String(protectedDrive));const name=document.createElement('strong');name.textContent=drive.model||drive.serial;button.append(name);for(const text of [drive.serial,(Number(drive.size_bytes)/1024**3).toFixed(1)+' GiB · '+(protectedDrive?'Protected · preserve':drive.state)]){const detail=document.createElement('small');detail.textContent=text;button.append(detail);}button.onclick=()=>chooseWorkspaceDrive(drive);button.ondragstart=event=>{if(protectedDrive){event.preventDefault();return;}event.dataTransfer.setData('application/x-baseline-shortcut',JSON.stringify({kind:'drive',id:drive.serial}));};drives.append(button);}const os=document.getElementById('os-shortcuts'),apps=document.getElementById('application-shortcuts');os.replaceChildren();apps.replaceChildren();for(const id of found.os_choices)for(const variant of ['desktop','server'])os.append(createShortcut({id,variant,name:'Ubuntu 24.04 '+variant,icon:'/installer-icons/'+id+'.svg'},'os'));for(const item of found.application_entries)apps.append(createShortcut(item,'app'));document.getElementById('os-count').textContent=os.children.length;document.getElementById('application-count').textContent=apps.children.length;renderWorkspaceChoices();const selected=found.selected_serial||new URLSearchParams(location.search).get('continue_serial');if(selected){const target=found.drives.find(d=>d.serial===selected);if(!target||found.protected_serials.includes(selected))throw Error('Selected installation drive is unavailable or protected');chooseWorkspaceDrive(target);}else document.getElementById('workspace-message').textContent='Drag a connected drive into the installation target.';}
async function startWorkspaceUpdate(){if(!workspaceTarget||workspaceBusy)return;workspaceBusy=true;document.getElementById('start-installation-update').disabled=true;try{await installerDraft.flush();await continueInstalledUpdate(workspaceTarget.serial);}catch(error){document.getElementById('update-status').textContent=error.message;}finally{workspaceBusy=false;document.getElementById('start-installation-update').disabled=!workspaceTarget;}}
for(const [id,kind] of [['installation-target','drive'],['environment-target','os'],['application-target','app']])installWorkspaceDrop(id,kind);
installerPhase('discovery');
loadWorkspaceCatalog().then(async()=>{await loadInstallerDisplay();const continuation=new URLSearchParams(location.search).get('continue_serial');if(continuation)startWorkspaceUpdate();}).catch(error=>{document.getElementById('workspace-message').textContent='Discovery failed: '+error.message;document.getElementById('start-installation-update').disabled=true;});
""".encode()

def render():
    import structured_controls
    import configuration_draft_ui
    import installer_desktop
    page = br'''<!doctype html><html><head><meta charset="utf-8"><title>Installer plan</title>
<style>body{font-family:system-ui;max-width:1000px;margin:2rem auto;padding:1rem;background:#10151e;color:#eee}textarea{box-sizing:border-box;width:100%;min-height:26rem;font-family:monospace}button{padding:.7rem;margin:.4rem 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#8ac8ff}.baseline-nav{display:flex;flex-wrap:wrap;gap:.5rem;margin-bottom:1.5rem}</style></head><body>
<h1>Installer plan</h1>
<p>Discover enrolled drives and fill in editable storage, Ubuntu and application choices. Validate again after editing: each request checks the drives present now.</p>
<p><strong>Plan preview and export execute no stages.</strong> They do not format drives, mount volumes, install an OS or launch applications. The separate installed-drive update below requires a completed source snapshot and human confirmation. General new-install stage execution remains unfinished.</p>
<p id="draft-status" role="status" aria-live="polite"></p><button type="button" id="draft-retry" hidden>Retry loading draft</button>
<fieldset id="draft-fields" disabled style="border:0;padding:0;margin:0"><button type="button" onclick="run('autofill')">Discover and autofill</button>
<label for="installation-serial">Independent installation drive serial</label><input id="installation-serial">
<button type="button" onclick="run('single-drive')">Plan a complete installation on this drive</button>
<p>Autofill replaces the editor contents. Changes save as your current draft. Export a plan to keep an additional copy before starting over.</p>
<label for="plan">Build choices</label><details><summary>Advanced JSON override</summary><textarea id="plan" spellcheck="false" aria-describedby="choices" disabled></textarea></details>
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
</fieldset>
<section aria-labelledby="input-title"><h2 id="input-title">Installation inputs</h2>
<p>Capture the saved plan, recipe, current settings and code. This runs a durable preparation job and checks its files. Missing publisher sources and target packages are reported before installation. No drive is changed.</p>
<button type="button" id="prepare-inputs" onclick="prepareInputs()">Prepare installation inputs</button>
<p id="input-status" role="status" aria-live="polite"></p><ul id="input-errors"></ul>
<p><a href="/workloads">Preparation job history</a></p></section>
<section><h2>Update an existing installation</h2>
<p>Choose the previously installed drive by serial and a completed input-preparation job. This refreshes Baseline and boot files using online package sources. Existing user/application volumes and credentials are retained. New OS/application selections are not provisioned by this update; verify boot and workloads afterward.</p>
<label for="update-serial">Installed drive serial</label><input id="update-serial">
<label for="update-input-job">Completed preparation job ID</label><input id="update-input-job">
<button type="button" onclick="reviewUpdate()">Review installed-drive update</button>
<p id="update-status" role="status" aria-live="polite"></p>
<dialog id="update-confirm"><form onsubmit="confirmUpdate(event)">
<h2>Confirm this installation update</h2><pre id="update-summary"></pre>
<p>Type <strong id="update-phrase"></strong>:</p><input id="update-typed" required autocomplete="off">
<label for="update-secret">Machine root password or recovery passphrase</label>
<input id="update-secret" type="password" required autocomplete="current-password">
<p>Privileged execution also uses the operating system's native authorization dialog.</p>
<button type="submit">Confirm update</button><button type="button" onclick="document.getElementById('update-confirm').close()">Cancel</button>
</form></dialog></section>
<script>
let epoch=0,validated=null,candidates=[];
let updateChallenge=null;
async function updatePost(url,body){const response=await fetch(url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const result=await response.json();if(!response.ok)throw Error(result.detail||result.message||'Update refused');return result;}
async function reviewUpdate(native=false){
 const status=document.getElementById('update-status');
 try{const result=await updatePost('/install-plan/update',{serial:document.getElementById('update-serial').value,job_id:document.getElementById('update-input-job').value});
  updateChallenge=result.challenge;document.getElementById('update-summary').textContent=updateChallenge.summary;
  document.getElementById('update-phrase').textContent=updateChallenge.phrase;
  document.getElementById('update-typed').value='';document.getElementById('update-secret').value='';
  if(native){
   installerPhase('authorization');status.textContent='Selected drive verified. Requesting native system authorization...';
   await new Promise(resolve=>setTimeout(resolve,(updateChallenge.min_wait+1)*1000));
   const submitted=await updatePost('/install-plan/execute-native',{challenge_id:updateChallenge.id});
   installerPhase('deployment');await watchInstalledUpdate(submitted.job_id);
  }else{document.getElementById('update-confirm').showModal();status.textContent='Review and confirm the selected drive update.';}

 }catch(error){status.textContent=error.message;}
}
async function watchInstalledUpdate(jobId){
 const status=document.getElementById('update-status');
 for(;;){
  const response=await fetch('/workloads/job?job_id='+encodeURIComponent(jobId),{credentials:'same-origin',cache:'no-store'});
  const job=await response.json();if(!response.ok)throw Error(job.error||'Update status unavailable');
  status.textContent='Installed-drive update '+job.state+'. '+((job.result||{}).message||'');
  if(job.state==='completed'){installerPhase('boot');status.textContent+=' Deployment complete; physical boot and runtime checks remain pending.';return;}
  if(['failed','interrupted','reviewed'].includes(job.state))throw Error((job.result||{}).message||'Update '+job.state);
  await new Promise(resolve=>setTimeout(resolve,1000));
 }
}
async function continueInstalledUpdate(serial){
 const status=document.getElementById('update-status');
 try{
  if(!/^[A-Za-z0-9._-]{4,40}$/.test(serial))throw Error('Invalid continuation serial');
  document.getElementById('update-serial').value=serial;
  installerPhase('source');status.textContent='Automatically preparing the selected installed drive...';
  const submitted=await updatePost('/install-plan/continue',{serial,request_id:'continue-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)});
  document.getElementById('update-input-job').value=submitted.job_id;
  for(;;){
   const response=await fetch('/workloads/job?job_id='+encodeURIComponent(submitted.job_id),{credentials:'same-origin',cache:'no-store'});
   const job=await response.json();if(!response.ok)throw Error(job.error||'Preparation status unavailable');
   status.textContent='Automatic update preparation: '+job.state;
   if(job.state==='completed')break;
   if(['failed','interrupted','reviewed'].includes(job.state))throw Error((job.result||{}).message||'Preparation '+job.state);
   await new Promise(resolve=>setTimeout(resolve,1000));
  }
  await reviewUpdate(true);
 }catch(error){status.textContent='Automatic continuation stopped: '+error.message;}
}
async function confirmUpdate(event){
 event.preventDefault();const status=document.getElementById('update-status'),secret=document.getElementById('update-secret');
 try{const result=await updatePost('/drive-admin/confirm',{challenge_id:updateChallenge.id,typed:document.getElementById('update-typed').value,secret:secret.value});
  secret.value='';document.getElementById('update-confirm').close();status.textContent='Installation update submitted. Follow its durable progress in Workload jobs.';
  if(result.job_id){const link=document.createElement('a');link.href='/workloads';link.textContent=' Open update job history';status.append(link);}
 }catch(error){status.textContent=error.message;secret.value='';}
}
const editor=document.getElementById('plan'),status=document.getElementById('status'),output=document.getElementById('result'),exportButton=document.getElementById('export');
const choiceEditor=new BaselineStructuredEditor(editor,{variant:['desktop','server'],os:['ubuntu-24.04']});
function invalidate(){epoch++;validated=null;exportButton.disabled=true;output.textContent='';status.textContent='Choices changed; validate against current drives.';}
editor.addEventListener('input',invalidate);
const installerDraft=baselineDraft({endpoint:'/install-plan/draft',read:()=>JSON.parse(editor.value),restore:value=>choiceEditor.set(value),inputs:[editor]});
async function prepareInputs(){
 const button=document.getElementById('prepare-inputs'),message=document.getElementById('input-status'),errors=document.getElementById('input-errors');
 button.disabled=true;errors.replaceChildren();
 try{
  const revision=await installerDraft.flush();
  message.textContent='Preparing saved revision '+revision+'...';
  const response=await fetch('/install-plan/prepare-inputs',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision,request_id:'inputs-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)})});
  const result=await response.json();if(!response.ok)throw Error(result.message||'Preparation refused');
  document.getElementById('update-input-job').value=result.job_id;
  for(;;){
   const stateResponse=await fetch('/workloads/job?job_id='+encodeURIComponent(result.job_id),{cache:'no-store'});
   const state=await stateResponse.json();if(!stateResponse.ok)throw Error(state.message||'Job unavailable');
   const job=state.job||state;
   message.textContent='Input preparation '+job.state+'. '+(job.message||'');
   if(['completed','failed','interrupted'].includes(job.state)){
    if(job.state!=='completed')throw Error('Preparation '+job.state+'. Inspect the job in Preparation job history; no installation was started.');
    break;
   }
   await new Promise(resolve=>setTimeout(resolve,1000));
  }
  const reportResponse=await fetch('/install-plan/input-bundle?job_id='+encodeURIComponent(result.job_id),{cache:'no-store'});
  const report=await reportResponse.json();if(!reportResponse.ok)throw Error(report.message||'Bundle verification failed');
  const checks=report.report||report;
  message.textContent=checks.ready?'Inputs verified. Installation execution remains unfinished.':'Code and configuration captured. Installation blocked by these missing inputs:';
  for(const error of checks.errors||[]){const item=document.createElement('li');item.textContent=error;errors.append(item);}
 }catch(error){message.textContent=error.message;}
 finally{button.disabled=false;}
}
async function run(action){
 const version=++epoch;validated=null;exportButton.disabled=true;output.textContent='';
 try{
  const body={action};if(action==='single-drive'){body.serial=document.getElementById('installation-serial').value;}else if(action!=='autofill'){if(new TextEncoder().encode(editor.value).length>65536)throw Error('Plan exceeds 64 KiB');body.plan=JSON.parse(editor.value);}
  if(action==='map_appdata'){body.persona=document.getElementById('persona').value;body.serial=document.getElementById('serial').value;body.partuuid=document.getElementById('partuuid').value;}
  status.textContent='Checking current drives...';
  const response=await fetch('/install-plan/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result=await response.json();if(version!==epoch)return;
  if(!response.ok||!result.ok)throw Error((result.errors||[result.message||'Plan refused']).join('\n'));
  candidates=result.appdata_candidates||[];const target=document.getElementById('target');target.replaceChildren();
  const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent=candidates.length?'Choose an existing AppData target':'No unique ready AppData volumes found';target.append(placeholder);
  for(const [index,item] of candidates.entries()){const option=document.createElement('option');option.value=String(index);option.textContent=item.persona+' - '+item.volume+' on '+item.model+' ('+item.serial+')';target.append(option);}
  if(action==='autofill'||action==='single-drive'||action==='map_appdata'){choiceEditor.set(result.plan);choiceEditor.sync();}
  output.textContent=JSON.stringify(result.stages||{notes:result.plan.notes||[],errors:result.errors},null,2);
  status.textContent=result.valid?'Valid against current discovery. Nothing executed.':result.errors.join('\n');
  if(result.valid){validated=JSON.stringify(result.plan,null,2)+'\n';exportButton.disabled=false;}
 }catch(error){if(version===epoch)status.textContent=error.message;}
}
function chooseTarget(){const value=document.getElementById('target').value;if(value==='')return;const item=candidates[Number(value)];if(!item)return;for(const field of ['persona','serial','partuuid'])document.getElementById(field).value=item[field];}
function download(){if(!validated)return;const url=URL.createObjectURL(new Blob([validated],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='baseline-install-plan.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
</script></body></html>'''
    page=page.replace(b'<p id="update-status" role="status" aria-live="polite"></p>',b'',1)
    page=page.replace(b'<h1>Installer plan</h1>',_WORKSPACE_HTML+b'<h1>Installer plan</h1>',1)
    page=page.replace(b'</style>',b'</style>'+_WORKSPACE_CSS,1)
    page=page.replace(b'<script>\nlet epoch',b'</details><script>\nlet epoch',1)
    page=page.replace(b'<div id="workspace-message"',installer_desktop.HTML+b'<div id="workspace-message"',1)
    page=page.replace(b'</head>',installer_desktop.CSS+b'</head>',1)
    page=page.replace(b'</script></body>',_WORKSPACE_JS+installer_desktop.JS+b'</script></body>',1)
    return page.replace(b'<script>\nlet epoch', (structured_controls.script()+configuration_draft_ui.script()).encode()+b'<script>\nlet epoch')
