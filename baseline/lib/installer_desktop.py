"""Installer display preferences and shortcut pages; never workload execution."""
import re


def validate(document):
    """Reject malformed layouts before owner-scoped durable storage."""
    def fail(message):
        raise ValueError('Installer display: ' + message)

    def identifier(value):
        return isinstance(value, str) and re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', value)

    def refs(values):
        if not isinstance(values, list) or len(values) > 256 or len(set(v for v in values if isinstance(v, str))) != len(values):
            fail('object references must be a unique list of at most 256 objects')
        if any(not isinstance(v, str) or not re.fullmatch(r'(app|os|drive):[A-Za-z0-9._:-]{1,100}', v) for v in values):
            fail('invalid object reference')

    if set(document) != {'version', 'display_mode', 'manager_mode', 'active_page', 'pages'}:
        fail('unsupported or missing layout fields')
    if document['version'] != 1 or document['display_mode'] not in ('workspace', 'desktop') or document['manager_mode'] not in ('full', 'split'):
        fail('unsupported display version or mode')
    pages = document['pages']
    if not isinstance(pages, list) or not 1 <= len(pages) <= 64:
        fail('choose between 1 and 64 pages')
    ids = set()
    for page in pages:
        if not isinstance(page, dict) or set(page) != {'id', 'name', 'kind', 'desktop', 'groups', 'configuration'}:
            fail('invalid page fields')
        if not identifier(page['id']) or page['id'] in ids:
            fail('page IDs must be unique')
        ids.add(page['id'])
        if not isinstance(page['name'], str) or not 1 <= len(page['name'].strip()) <= 80 or page['kind'] not in ('baseline', 'vm', 'container'):
            fail('invalid page name or type')
        refs(page['desktop'])
        if not isinstance(page['configuration'], dict):
            fail('object configuration must be an object')
        refs(list(page['configuration']))
        if any(not isinstance(v, dict) for v in page['configuration'].values()):
            fail('each object configuration must be an object')
        groups = page['groups']
        if not isinstance(groups, list) or len(groups) > 64:
            fail('too many groups')
        group_ids = set()
        for group in groups:
            if not isinstance(group, dict) or set(group) != {'id', 'name', 'objects', 'visible', 'last_object'}:
                fail('invalid group fields')
            if not identifier(group['id']) or group['id'] in group_ids:
                fail('group IDs must be unique')
            group_ids.add(group['id'])
            if not isinstance(group['name'], str) or not 1 <= len(group['name'].strip()) <= 80 or type(group['visible']) is not bool:
                fail('invalid group name or visibility')
            refs(group['objects'])
            if group['last_object'] is not None and group['last_object'] not in group['objects']:
                fail('remembered group icon must belong to the group')
    if document['active_page'] not in ids:
        fail('active page must exist')


HTML = r'''<button id="display-mode-open" class="display-mode-open" type="button" aria-label="Edit Installer display mode"><img src="/installer-icons/edit.svg" alt=""><span>Edit</span></button>
<dialog id="desktop-display-dialog"><h2>Installer display</h2><div class="display-toolbar">
<label>Installer display <select id="installer-display-mode" disabled><option value="workspace">Current workspace</option><option value="desktop">Phone desktop &amp; taskbar</option></select></label>
<span id="display-save-status" role="status" aria-live="polite">Loading display preferences…</span>
<button id="reload-display" type="button" hidden onclick="location.reload()">Reload saved layout</button>
</div><div class="dialog-actions"><button type="button" onclick="document.getElementById('desktop-display-dialog').close()">Done</button></div></dialog>
<section id="phone-desktop" hidden aria-label="VM and container desktop">
<aside id="desktop-left-rail" aria-label="Installer sections"></aside>
<div id="environment-switcher"></div><nav id="rail-object-groups" aria-label="Environment sections"></nav>
<main id="desktop-page"></main>
</section>
<dialog id="edit-taskbar"><h2>Edit taskbar group</h2>
<label>Group title<input id="taskbar-group-title" maxlength="80"></label>
<div id="taskbar-order"></div><div class="dialog-actions">
<button id="hide-taskbar-group" type="button">Remove group from bar</button>
<button type="button" onclick="document.getElementById('edit-taskbar').close()">Done</button></div></dialog>

<dialog id="new-desktop-page"><form id="new-desktop-page-form">
<h2>Add a VM or container page</h2>
<label>Page name<input id="desktop-page-name" required maxlength="80"></label>
<label>Environment type<select id="desktop-page-kind"><option value="vm">Virtual machine</option><option value="container">Container</option></select></label>
<p>This creates an Installer configuration page. Provisioning uses the native workload controls.</p>
<p id="desktop-page-error" role="status"></p><div class="dialog-actions"><button type="button" onclick="document.getElementById('new-desktop-page').close()">Cancel</button><button id="save-desktop-page" class="primary" type="submit">Add page</button></div>
</form></dialog>
<dialog id="new-taskbar-group-dialog"><form id="new-taskbar-group-form"><h2>New taskbar group</h2><label>Group title<input id="new-taskbar-group-name" required maxlength="80"></label><p id="new-taskbar-group-error" role="status"></p><div class="dialog-actions"><button type="button" onclick="document.getElementById('new-taskbar-group-dialog').close()">Cancel</button><button id="save-taskbar-group" type="submit" class="primary">Create group</button></div></form></dialog>
<dialog id="environment-component-details"><h2 id="component-detail-title"></h2><p id="component-detail-description"></p><p id="component-detail-status" role="status"></p><p><a id="component-detail-link" href="#" hidden>Open related settings</a></p><div class="dialog-actions"><button type="button" onclick="document.getElementById('environment-component-details').close()">Done</button></div></dialog>
<dialog id="environment-settings-dialog"><form id="environment-settings-form"><h2 id="environment-settings-title"></h2><p id="environment-settings-kind"></p><label>VM / container name<input id="environment-settings-name" required maxlength="80"></label><p id="environment-settings-status" role="status">Setup draft · not provisioned</p><h3>Configuration for this environment</h3><div id="environment-settings-components" class="environment-components"></div><div class="dialog-actions"><button type="button" onclick="document.getElementById('environment-settings-dialog').close()">Done</button><button type="submit" class="primary">Save environment</button></div></form></dialog>'''.encode()

CSS = r'''<style>
[hidden]{display:none!important}.display-toolbar{display:flex;align-items:center;flex-wrap:wrap;gap:16px;margin:20px 0}.display-toolbar label{font-size:13px}.display-toolbar select{margin-left:10px;padding:9px;background:#17273b;color:#eef4ff;border:1px solid #70819a;border-radius:10px}#display-save-status{font-size:12px;color:#b6c8df}
body[data-installer-mode=desktop] .workspace-columns,body[data-installer-mode=desktop] .workspace-selection{display:none}
#phone-desktop{border:1px solid #ffffff26;background:#11213d55;border-radius:24px;overflow:hidden;min-height:500px}
#desktop-page{padding:24px;min-height:430px}
</style><style>
.desktop-tools{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:14px}.desktop-tools button,.manager-tools button,.manager-tools select{background:#1a304b;color:#e6efff;border:1px solid #627894;border-radius:10px;padding:9px 14px}
.desktop-taskbar{position:relative;display:flex;align-items:flex-start;justify-content:flex-end;gap:8px;padding:12px;margin-bottom:20px;min-height:112px;background:#14284099;border-radius:22px}
#taskbar-row{display:flex;min-width:0;flex:1;align-items:flex-start}#taskbar-scroll{display:flex;gap:10px;overflow-x:auto;min-width:0;flex:1;overscroll-behavior:contain;scrollbar-width:thin}
#taskbar-scroll .desktop-shortcut{flex:0 0 94px}.taskbar-fixed{flex:0 0 86px;margin:0;background:#213e59;color:#f1f7ff;border:1px solid #7093b3;border-radius:16px;min-height:96px;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:8px;font-size:12px}#taskbar-edit b{font-size:30px}#group-corner{position:relative;touch-action:none;user-select:none}#group-corner img{width:42px;height:42px;object-fit:contain}#group-corner .up-arrow{position:absolute;top:-13px;right:30px;font-size:18px}#group-corner .right-arrow{position:absolute;top:10px;right:-10px;font-size:18px}#group-corner small{font-size:10px;color:#adcae6}
#taskbar-groups{position:absolute;z-index:3;top:112px;right:12px;max-height:320px;overflow-y:auto;min-width:220px;padding:10px;border-radius:18px;background:#14273df5;border:1px solid #90a8c3;box-shadow:0 18px 42px #0006}#taskbar-groups button{display:flex;align-items:center;gap:12px;width:100%;background:transparent;color:#e6f0ff;border:0;text-align:left;padding:12px;border-radius:10px}#taskbar-groups button:hover{background:#355774}#taskbar-groups img{width:32px;height:32px;object-fit:contain}
#desktop-body{min-height:280px;touch-action:pan-y}#desktop-body h2{font-size:22px}.desktop-body-icons{max-width:100%;grid-template-columns:repeat(auto-fill,minmax(95px,1fr))}.desktop-layout{display:grid;grid-template-columns:minmax(0,1fr);gap:20px}.desktop-layout.manager-split{grid-template-columns:minmax(0,1fr) minmax(320px,.85fr)}.desktop-layout.manager-full #desktop-body{display:none}#object-manager{padding:20px;border:1px solid #839abf;background:#14263de6;border-radius:20px;min-width:0;max-height:65vh;overflow-y:auto}.manager-tools{display:flex;flex-wrap:wrap;align-items:center;gap:10px}.manager-tools h2{flex:1;margin:0}.manager-tools input{min-width:120px;background:#102039;color:#eef5ff;border:1px solid #8194af;border-radius:8px;padding:10px;width:100%}.manager-type h3{font-size:14px;margin-top:24px;color:#b5cbe5}.manager-restored-groups{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}.manager-restored-groups button{background:#223c58;border:1px solid #728cab;color:#e3edfa;border-radius:10px;padding:8px}.order-row{display:flex;gap:8px;align-items:center;border-bottom:1px solid #44536a;padding:8px}.order-row span{flex:1}.order-row button{padding:8px;margin:0}
@media(max-width:900px){.desktop-layout.manager-split{grid-template-columns:1fr}#object-manager{max-height:70vh}}
@media(max-width:680px){#desktop-page{padding:12px}.desktop-taskbar{padding:10px 16px 10px 8px}.taskbar-fixed{flex-basis:74px}#taskbar-scroll .desktop-shortcut{flex-basis:86px}}
</style>'''.encode()

# The desktop mode is a full-browser shell.  These rules deliberately replace
# the earlier centered-card geometry while leaving Current workspace intact.
CSS += r'''<style>
body[data-installer-mode=desktop]{margin:0!important;padding:0!important;overflow:hidden!important;background:#111820}
body[data-installer-mode=desktop] .installer-workspace{width:100vw;max-width:none;margin:0;padding:0}
body[data-installer-mode=desktop] .workspace-header,body[data-installer-mode=desktop] .workspace-columns,body[data-installer-mode=desktop] .workspace-selection,body[data-installer-mode=desktop] #advanced-installer{display:none!important}
body[data-installer-mode=desktop] .baseline-nav{display:none!important}
.display-mode-open{position:fixed;z-index:60;left:4px;bottom:4px;width:58px;height:58px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;color:#e4edf7;background:#1b3047;border:1px solid #7791ab;border-radius:7px;font-size:9px}
.display-mode-open img{width:25px;height:25px;object-fit:contain}
#desktop-display-dialog{z-index:70}
#environment-settings-dialog{width:min(1100px,calc(100vw - 24px));max-height:88vh;overflow:auto}
#environment-settings-dialog .environment-components{max-width:none;margin:14px 0}
.environment-heading{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap}.environment-heading button{display:flex;align-items:center;gap:8px;padding:8px 12px;color:#eaf1f8;background:#1a304b;border:1px solid #627894;border-radius:10px}.environment-heading button img{width:22px;height:22px}
#desktop-display-dialog .display-toolbar{display:flex;flex-direction:column;align-items:stretch;gap:12px;margin:8px 0 0}
#desktop-display-dialog .display-toolbar label{font-size:14px}
#desktop-display-dialog .display-toolbar select{width:100%;margin:8px 0 0}
#display-save-status{font-size:12px;color:#b6c8df}
body[data-installer-mode=desktop] #phone-desktop{position:fixed;inset:0;z-index:40;display:block!important;width:100vw;height:100dvh;min-height:0;margin:0;padding:0;border:0;border-radius:0;overflow:hidden;background:#182539}
#desktop-left-rail{position:absolute;z-index:4;left:0;top:64px;bottom:0;width:72px;overflow-y:auto;overflow-x:hidden;background:#090e18eF;border-right:1px solid #52617d;scrollbar-width:thin}
#desktop-left-rail .baseline-nav{display:none!important}
#environment-switcher{position:absolute;z-index:6;left:0;top:0;width:72px;height:64px;display:grid;place-items:center;background:#111820;border-bottom:1px solid #52617d}
#environment-switcher select{width:64px;height:50px;padding:3px;color:#edf4ff;background:#20354d;border:1px solid #7590ad;border-radius:7px;font-size:10px}
#rail-object-groups{position:fixed;z-index:7;left:0;top:64px;bottom:0;width:72px;overflow-y:auto;display:flex;flex-direction:column;align-items:stretch;gap:3px;padding:5px 3px;background:#090e18ef;border-right:1px solid #52617d}
#rail-object-groups button,.rail-route{display:flex;min-height:58px;width:100%;flex-direction:column;align-items:center;justify-content:center;gap:3px;padding:3px 1px;color:#d9e2ed;text-decoration:none;text-align:center;font-size:9px;line-height:1.08;background:transparent;border:1px solid transparent;border-radius:6px}
#rail-object-groups button:hover,#rail-object-groups button[aria-pressed=true],.rail-route:hover{background:#29425b;border-color:#6a8ba9}
#rail-object-groups img,.rail-route img{width:25px;height:25px;object-fit:contain}
#add-desktop-page{font-size:17px!important}
#desktop-left-rail .baseline-nav{display:flex;flex-direction:column;align-items:stretch;gap:2px;margin:0;padding:5px 2px 10px;border:0;background:transparent}
#desktop-left-rail .baseline-nav>a{display:flex;min-height:54px;padding:4px 1px;align-items:center;justify-content:center;flex-direction:column;gap:2px;overflow:hidden;color:#d9e2ed;text-decoration:none;text-align:center;font-size:8px;line-height:1.05;border:1px solid transparent;border-radius:6px}
#desktop-left-rail .baseline-nav>a:hover,#desktop-left-rail .baseline-nav>a.active{background:#29425b;border-color:#6a8ba9}
#desktop-left-rail .baseline-nav:not(.show-all)>a:nth-of-type(n+6){display:none}
#desktop-nav-more{display:block;width:100%;min-height:34px;padding:4px;color:#d9e2ed;background:transparent;border:1px solid transparent;border-radius:5px;font-size:9px}
#desktop-nav-more:hover{background:#29425b;border-color:#6a8ba9}
#desktop-left-rail .baseline-nav>a::before{content:"";width:25px;height:25px;flex:0 0 25px;background:url('/installer-icons/application.svg') center/contain no-repeat}
#desktop-left-rail .baseline-nav>a[href^="/settings"]::before{background-image:url('/installer-icons/rail-settings.svg')}
#desktop-left-rail .baseline-nav>a[href^="/admin"]::before{background-image:url('/installer-icons/rail-admin.svg')}
#desktop-left-rail .baseline-nav>a[href^="/recovery"]::before{background-image:url('/installer-icons/rail-recovery.svg')}
#desktop-left-rail .baseline-nav>a[href^="/drive-admin"]::before{background-image:url('/installer-icons/rail-drives.svg')}
#desktop-left-rail .baseline-nav>a[href^="/operations"]::before{background-image:url('/installer-icons/rail-operations.svg')}
#desktop-left-rail .baseline-nav>a[href^="/hardware"]::before{background-image:url('/installer-icons/rail-hardware.svg')}
#desktop-left-rail .baseline-nav>a[href^="/install-plan"]::before{background-image:url('/installer-icons/menu.svg')}
#desktop-left-rail .baseline-nav>form{margin:8px 0 0;padding:0 2px;border:0;background:transparent}
#desktop-left-rail .baseline-nav>form button{width:100%;padding:5px 1px;white-space:normal;font-size:8px;background:#17283c;color:#dce8f5;border:1px solid #536984;border-radius:6px}
#desktop-page{position:absolute;inset:64px 0 0 72px;margin:0;padding:0;min-height:0;overflow:hidden;background:#192944}
.desktop-tools{position:fixed;left:-10000px;top:0;width:1px;height:1px;overflow:hidden;gap:4px;margin:0}
.desktop-tools #open-object-manager{font-size:11px;padding:6px 9px}
.desktop-tools #add-desktop-page{font-size:11px;padding:6px 9px}
.desktop-taskbar{position:fixed;z-index:5;left:72px;right:0;top:0;height:64px;min-height:0;display:flex;align-items:stretch;justify-content:stretch;gap:0;margin:0;padding:4px 8px 3px 0;border-bottom:1px solid #35445b;background:#101115f2;border-radius:0}
#taskbar-row{height:100%;min-width:0;flex:1;align-items:stretch}
#taskbar-scroll{height:100%;align-items:stretch;gap:2px;padding:0 4px;overflow-x:auto;overflow-y:hidden;scrollbar-width:none}
#taskbar-scroll .desktop-shortcut{flex:0 0 58px;min-height:0;height:100%;gap:1px;padding:2px 3px;border-radius:4px}
#taskbar-scroll .desktop-shortcut img{width:26px;height:26px}
#taskbar-scroll .desktop-shortcut span{display:block;width:58px;max-width:58px;font-size:8px;line-height:1.05;overflow:hidden;text-overflow:clip;white-space:normal;overflow-wrap:anywhere}
#taskbar-edit.taskbar-fixed{flex:0 0 48px;width:48px;height:100%;min-height:0;gap:1px;padding:2px;background:#263d57;border-radius:5px;font-size:9px}
#taskbar-edit img,#group-corner img{width:24px;height:24px;object-fit:contain}
#taskbar-edit span{font-size:8px}
#group-corner.taskbar-fixed{position:relative;order:2;flex:0 0 48px;width:48px;height:100%;min-height:0;gap:1px;padding:2px;background:#263d57;border-radius:5px;font-size:8px}
#group-corner .up-arrow{top:0;right:8px;width:10px;height:10px;font-size:0;background:url('/installer-icons/arrow-up.svg') center/contain no-repeat}
#group-corner .right-arrow{top:9px;right:0;width:10px;height:10px;font-size:0;background:url('/installer-icons/arrow-right.svg') center/contain no-repeat}
#group-corner small{font-size:7px}
#taskbar-groups{position:fixed;z-index:9;top:66px;right:56px;max-height:min(65vh,580px);background:#142133f7;border-radius:6px}
#desktop-body{position:absolute;inset:0;min-height:0;overflow:auto;padding:22px 24px;touch-action:pan-y;background:linear-gradient(180deg,#243651ee,#1d2b40ee)}
#desktop-body h2{margin:0 0 8px;font-size:clamp(18px,2vw,26px)}
#desktop-body>p{margin:0 0 16px}
.environment-components{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;width:100%;margin:24px 0}
.environment-component{min-height:116px;display:flex;align-items:center;gap:14px;padding:16px;color:#edf3fb;text-align:left;background:#15253bd9;border:1px solid #70829a;border-radius:14px}
.environment-component.is-disabled{filter:grayscale(1);opacity:.55;cursor:not-allowed}
.environment-component img{width:42px;height:42px;object-fit:contain}.environment-component span{display:block}.environment-component strong{display:block;font-size:15px}.environment-component small{display:block;margin-top:6px;color:#b6c8df;font-size:12px}
.desktop-shortcut.is-disabled{filter:grayscale(1);opacity:.48;cursor:not-allowed}.desktop-shortcut.is-disabled img{filter:grayscale(1)}
.advanced-object-settings{margin:14px 0}.advanced-object-settings>summary{cursor:pointer;padding:10px 12px;color:#dce8f5;background:#1b2d43;border:1px solid #526a82;border-radius:8px}.advanced-object-settings[open]>summary{margin-bottom:12px}
.open-object-manager{display:flex;width:100%;height:54px;flex-direction:column;align-items:center;justify-content:center;gap:2px;margin:2px 0 6px;padding:2px;color:#e0ebf6;background:#1a2c40;border:1px solid #58718a;border-radius:6px;font-size:8px}
.open-object-manager img{width:25px;height:25px;object-fit:contain}
.desktop-body-icons{grid-template-columns:repeat(auto-fill,minmax(96px,118px));max-width:none}
.desktop-layout{position:absolute;inset:0;display:block;min-height:0;overflow:hidden;background:#1e2e46}
#desktop-layout.manager-full #desktop-body{display:block!important}
#object-manager{position:fixed;z-index:3;left:72px;right:0;top:25vh;bottom:8px;max-height:none;overflow:auto;padding:14px 18px 24px;background:#151617;border:0;border-top:1px solid #53576a;border-radius:0;color:#e5e5e5}
#object-manager{pointer-events:none}#object-manager>*{pointer-events:auto}
.desktop-layout.manager-split #object-manager{left:min(50vw,720px);top:64px}
.desktop-layout.manager-split #desktop-body{right:min(50vw,720px)}
.manager-tools{position:sticky;top:-14px;z-index:2;margin:-14px -18px 14px;padding:12px 18px;background:#18191bf5;border-bottom:1px solid #34363b}
.manager-tools h2{font-size:19px;font-weight:650;text-transform:lowercase}
.manager-categories{display:flex;gap:4px;overflow:auto;margin:0 0 12px}
.manager-categories button{padding:6px 11px;color:#dbe4ee;background:#20252c;border:1px solid #454c56;border-radius:3px;font-size:11px}
.manager-categories button[aria-pressed=true]{background:#31445e;border-color:#a6bed7}
.manager-type h3{padding:8px 14px;margin:8px 0 0;background:#222326;color:#e7e8eb;font-size:17px;text-transform:lowercase}
.manager-type .shortcut-grid{grid-template-columns:repeat(auto-fill,minmax(100px,130px));gap:3px;background:#18191a;padding:8px}
#object-manager .desktop-shortcut{min-height:96px;color:#e3e6eb}
.driver-catalog-error{margin:14px 0;padding:12px 14px;color:#ffd6ad;background:#32271e;border-left:3px solid #d28b4a;font-size:13px}
@media(max-width:900px){.desktop-layout.manager-split #object-manager{left:72px;top:64px}}
@media(max-width:680px){#desktop-left-rail{width:72px}#rail-object-groups{width:72px}#environment-switcher{width:72px}#desktop-page{left:72px}#object-manager{left:72px}.desktop-taskbar{left:72px}.desktop-tools{top:134px}.manager-tools{align-items:flex-start}.manager-tools h2{min-width:100%}#desktop-body{padding:14px 12px}.environment-components{grid-template-columns:minmax(0,1fr);gap:8px;margin:16px 0}.environment-component{min-height:82px;padding:12px}.environment-component img{width:36px;height:36px}.environment-component strong{font-size:14px}.environment-component small{font-size:12px}#taskbar-scroll .desktop-shortcut span{font-size:9px;line-height:1.1}}
</style>'''.encode()

JS = r'''
let installerDisplay=null,displayRevision=0,displaySaveQueue=Promise.resolve(),displayBlocked=false;
function activeDesktopPage(){return installerDisplay.pages.find(page=>page.id===installerDisplay.active_page);}
function defaultInstallerDisplay(){return {version:1,display_mode:'desktop',manager_mode:'split',active_page:'baseline',pages:[{id:'baseline',name:'testvm1',kind:'vm',desktop:[],groups:[],configuration:{}}]};}
async function persistInstallerDisplay(){
 const snapshot=structuredClone(installerDisplay);
 const save=displaySaveQueue.then(async()=>{
  if(displayBlocked)throw Error('Reload saved layout before editing again.');
  document.getElementById('display-save-status').textContent='Saving layout…';
  const result=await updatePost('/install-plan/display',{document:snapshot,revision:displayRevision});
  displayRevision=result.draft.revision;document.getElementById('display-save-status').textContent='Layout saved';
 });
 displaySaveQueue=save.catch(error=>{displayBlocked=true;document.getElementById('display-save-status').textContent='Layout not saved: '+error.message;document.getElementById('reload-display').hidden=false;});
 await save;
}
function renderInstallerDisplay(){
 if(!installerDisplay)return;
 document.body.dataset.installerMode=installerDisplay.display_mode;
 document.getElementById('installer-display-mode').value=installerDisplay.display_mode;
 document.getElementById('phone-desktop').hidden=installerDisplay.display_mode!=='desktop';
 const panel=document.getElementById('desktop-page');panel.removeAttribute('aria-labelledby');panel.replaceChildren();const heading=document.createElement('h2');heading.textContent=activeDesktopPage().name;panel.append(heading);
}
async function loadInstallerDisplay(){
 document.getElementById('display-mode-open').onclick=()=>document.getElementById('desktop-display-dialog').showModal();
 const response=await fetch('/install-plan/display',{credentials:'same-origin',cache:'no-store'}),result=await response.json();
 if(!response.ok)throw Error(result.message||'Display preferences unavailable');
 installerDisplay=result.draft?result.draft.document:defaultInstallerDisplay();displayRevision=result.draft?result.draft.revision:0;for(const page of installerDisplay.pages){if(page.id==='baseline'&&page.name==='Baseline'&&page.kind==='baseline'){page.name='testvm1';page.kind='vm';}const defaults=newDesktopGroups();for(const group of defaults)if(!page.groups.some(saved=>saved.id===group.id))page.groups.push(group);}
 const requestedMode=new URLSearchParams(location.search).get('display');
 if(requestedMode==='desktop'||requestedMode==='workspace')installerDisplay.display_mode=requestedMode;
 renderInstallerDisplay();const mode=document.getElementById('installer-display-mode');mode.disabled=false;
 document.getElementById('display-save-status').textContent=result.draft?'Saved layout loaded':'Choose an Installer display';
 mode.onchange=()=>{const url=new URL(location.href);url.searchParams.set('display',mode.value);location.assign(url.href);};
 if(requestedMode==='desktop'||requestedMode==='workspace')await persistInstallerDisplay();
}

let desktopGroupId='applications',taskbarOpen=true,groupPickerOpen=false,objectManagerOpen=false;
function desktopObjects(){
 const objects=[];
 for(const app of workspaceCatalog.application_entries)objects.push({...app,key:'app:'+app.id,kind:'app',type:'Applications'});
 for(const id of workspaceCatalog.os_choices)for(const variant of ['desktop','server'])objects.push({key:'os:'+id+':'+variant,id,variant,name:id.replaceAll('-',' ')+' '+variant,icon:'/installer-icons/'+id+'.svg',kind:'os',type:'Operating systems'});
 for(const drive of workspaceCatalog.drives){const protectedDrive=workspaceCatalog.protected_serials.includes(drive.serial);objects.push({key:'drive:'+drive.serial,id:drive.serial,name:drive.model||'Installation drive',icon:'/installer-icons/rail-drives.svg',kind:'drive',type:'Drives',drive,protected:protectedDrive});}
 return objects;
}
function desktopObject(key){return desktopObjects().find(object=>object.key===key)||{key,id:key,name:key+' (unavailable)',icon:'/installer-icons/application.svg',kind:key.split(':')[0],type:'Unavailable objects',unavailable:true};}
function newDesktopGroups(){const objects=desktopObjects(),types=['Applications','Operating systems','Drive assignment','Drivers','Proxmox','Hardware templates','Setup'],catalogType=type=>type==='Drive assignment'?'Drives':type;return types.map((type,index)=>{const refs=objects.filter(object=>object.type===catalogType(type)).map(object=>object.key);return {id:['applications','operating-systems','drives','drivers','proxmox','hardware','settings'][index],name:type,objects:refs,visible:true,last_object:refs.at(-1)||null};});}
const previousDefaultDisplay=defaultInstallerDisplay;
defaultInstallerDisplay=function(){const state=previousDefaultDisplay();state.pages[0].groups=newDesktopGroups();return state;};
function activeTaskbarGroup(){const groups=activeDesktopPage().groups;return groups.find(group=>group.id===desktopGroupId&&group.visible)||groups.find(group=>group.visible)||null;}
function displayButton(label,click){const button=document.createElement('button');button.type='button';button.textContent=label;button.onclick=click;return button;}
async function saveDesktopChange(){renderInstallerDisplay();try{await persistInstallerDisplay();}catch(error){}}
async function assignDesktopObject(object){
 const page=activeDesktopPage();if(object.unavailable)throw Error('Object is no longer available');if(object.protected)throw Error('Protected drive: preserve; no target selection performed');
 if(object.kind==='drive'){const drive=workspaceCatalog?.drives.find(item=>item.serial===object.id);if(!drive)throw Error('Drive is no longer in current discovery');chooseWorkspaceDrive(drive);page.configuration[object.key]={...(page.configuration[object.key]||{}),selected:true};}
 else if(object.kind==='app'){if(!page.desktop.includes(object.key))page.desktop.push(object.key);if(!await addShortcutChoice(object,'app'))throw Error('Application choice was not saved in the Installer plan');}
 else if(object.kind==='os'){if(!await addShortcutChoice({id:object.id,variant:object.variant,environmentName:page.name},'os'))throw Error('Operating system choice was not saved in the Installer plan');page.configuration[object.key]={...(page.configuration[object.key]||{}),selected:true,os:object.id,variant:object.variant};}
 renderInstallerDisplay();await persistInstallerDisplay();
}
function desktopShortcut(object){
 const button=document.createElement('button');button.type='button';button.className='desktop-shortcut'+(object.unavailable||object.protected?' is-disabled':'');button.dataset.objectKey=object.key;button.draggable=!object.unavailable&&!object.protected;if(object.unavailable||object.protected){button.setAttribute('aria-disabled','true');button.title=object.protected?'Protected drive: preserve; it cannot be selected as an installation target':'Unavailable: this object is not in current discovery';}
 button.append(shortcutImage(object.icon));const name=document.createElement('span');name.textContent=object.name;button.append(name);if(object.kind==='app'&&!object.unavailable)button.title=object.name+' · available to add; installation is not yet verified';
 button.onclick=()=>object.unavailable||object.protected?showDesktopObjectDetails(object):assignDesktopObject(object).catch(error=>{document.getElementById('workspace-message').textContent='Choice was not saved: '+error.message;});button.oncontextmenu=event=>{event.preventDefault();showDesktopObjectDetails(object);};
 button.onkeydown=event=>{if(event.key==='ContextMenu'||event.shiftKey&&event.key==='F10'){event.preventDefault();showDesktopObjectDetails(object);}};
 button.ondragstart=event=>event.dataTransfer.setData('application/x-baseline-desktop-object',object.key);
 return button;
}
function renderDesktopTaskbar(){
 const group=activeTaskbarGroup();if(group)desktopGroupId=group.id;
 const corner=document.getElementById('group-corner');corner.replaceChildren();
 const up=document.createElement('span');up.className='up-arrow';up.textContent='↑';up.setAttribute('aria-hidden','true');const right=document.createElement('span');right.className='right-arrow';right.textContent='→';right.setAttribute('aria-hidden','true');corner.append(up,right);
 if(group&&group.last_object)corner.append(shortcutImage(desktopObject(group.last_object).icon));else corner.append(shortcutImage('/installer-icons/menu.svg'));
 const label=document.createElement('span');label.textContent=group?group.name:'Groups';corner.append(label);corner.setAttribute('aria-expanded',String(taskbarOpen));corner.setAttribute('aria-label',(group?group.name:'Groups')+'. Swipe left or right for icons, up or down for groups; hold to restore the remembered icon.');
 document.getElementById('taskbar-row').hidden=!taskbarOpen||!group;
 const scroll=document.getElementById('taskbar-scroll');scroll.replaceChildren();
 if(group?.id==='settings')for(const [kind,title,icon]of [['drive','Drive assignment','/installer-icons/rail-drives.svg'],['platform','Proxmox','/installer-icons/rail-admin.svg'],['os','Operating system','/installer-icons/ubuntu-24.04.svg'],['hardware','Hardware profile','/installer-icons/rail-hardware.svg'],['drivers','Drivers','/installer-icons/rail-hardware.svg'],['app','Applications','/installer-icons/menu.svg']]){const shortcut=document.createElement('button');shortcut.type='button';shortcut.className='desktop-shortcut'+(kind==='drivers'?' is-disabled':'');shortcut.dataset.componentKind=kind;if(kind==='drivers'){shortcut.setAttribute('aria-disabled','true');shortcut.title='No verified universal driver package is available';}shortcut.innerHTML='<img alt=""><span></span>';shortcut.querySelector('img').src=icon;shortcut.querySelector('span').textContent=title;shortcut.onclick=()=>openEnvironmentComponent(kind);shortcut.oncontextmenu=event=>{event.preventDefault();openEnvironmentComponent(kind);};scroll.append(shortcut);}
 if(group)for(const key of group.objects){const object=desktopObject(key),shortcut=desktopShortcut(object);shortcut.addEventListener('click',()=>{group.last_object=key;persistInstallerDisplay().catch(()=>{});});scroll.append(shortcut);}
 if(group?.id==='drivers'){const driver=document.createElement('button');driver.type='button';driver.className='desktop-shortcut is-disabled';driver.dataset.driverPackage='unavailable';driver.setAttribute('aria-disabled','true');driver.title='No verified universal driver package is available';driver.innerHTML='<img src="/installer-icons/application.svg" alt=""><span>Universal drivers</span>';driver.onclick=()=>openEnvironmentComponent('drivers');driver.oncontextmenu=event=>{event.preventDefault();openEnvironmentComponent('drivers');};scroll.append(driver);}
 const picker=document.getElementById('taskbar-groups');picker.hidden=!groupPickerOpen;picker.replaceChildren();
 for(const item of activeDesktopPage().groups.filter(item=>item.visible)){const button=displayButton(item.name,()=>{desktopGroupId=item.id;groupPickerOpen=false;renderDesktopTaskbar();});if(item.last_object)button.prepend(shortcutImage(desktopObject(item.last_object).icon));picker.append(button);}
 picker.append(displayButton('Object Manager',()=>{groupPickerOpen=false;managerCategory='All setup objects';objectManagerOpen=true;renderInstallerDisplay();}));
}
function cornerGestures(corner){
 let start=null,timer=null,handled=false;
 corner.onpointerdown=event=>{if(event.button!==0)return;start={x:event.clientX,y:event.clientY};handled=false;corner.setPointerCapture(event.pointerId);timer=setTimeout(()=>{handled=true;taskbarOpen=true;groupPickerOpen=false;renderDesktopTaskbar();document.getElementById('display-save-status').textContent='Remembered group icon pinned; scroll the row. Edit stays at the end.';},550);};
 corner.onpointermove=event=>{if(start&&Math.hypot(event.clientX-start.x,event.clientY-start.y)>12)clearTimeout(timer);};
 corner.onpointerup=event=>{clearTimeout(timer);if(!start)return;const dx=event.clientX-start.x,dy=event.clientY-start.y;if(Math.max(Math.abs(dx),Math.abs(dy))>35){handled=true;if(Math.abs(dx)>Math.abs(dy)){taskbarOpen=dx<0;groupPickerOpen=false;}else{groupPickerOpen=dy<0;}renderDesktopTaskbar();}start=null;};
 corner.onpointercancel=()=>{clearTimeout(timer);start=null;handled=true;};
 corner.onclick=()=>{if(handled){handled=false;return;}taskbarOpen=!taskbarOpen;renderDesktopTaskbar();};
 corner.oncontextmenu=event=>{event.preventDefault();groupPickerOpen=!groupPickerOpen;renderDesktopTaskbar();};
}
function editDesktopTaskbar(){
 const group=activeTaskbarGroup();if(!group)return;const dialog=document.getElementById('edit-taskbar'),title=document.getElementById('taskbar-group-title');title.value=group.name;
 title.onchange=()=>{if(!title.value.trim())return;group.name=title.value.trim().slice(0,80);saveDesktopChange();};
 const renderOrder=()=>{const list=document.getElementById('taskbar-order');list.replaceChildren();for(const [index,key]of group.objects.entries()){
  const row=document.createElement('div');row.className='order-row';const label=document.createElement('span');label.textContent=desktopObject(key).name;row.append(label);
  for(const [label,offset]of [['↑',-1],['↓',1]]){const button=displayButton(label,async()=>{const next=index+offset;[group.objects[index],group.objects[next]]=[group.objects[next],group.objects[index]];await saveDesktopChange();renderOrder();});button.disabled=index+offset<0||index+offset>=group.objects.length;button.setAttribute('aria-label',(offset<0?'Move earlier: ':'Move later: ')+desktopObject(key).name);row.append(button);}
  row.append(displayButton('Remove',async()=>{group.objects=group.objects.filter(object=>object!==key);if(group.last_object===key)group.last_object=group.objects.at(-1)||null;await saveDesktopChange();renderOrder();}));list.append(row);
 }};renderOrder();document.getElementById('hide-taskbar-group').onclick=async()=>{group.visible=false;taskbarOpen=false;dialog.close();await saveDesktopChange();};dialog.showModal();
}
let managerCategory='All setup objects';
function renderDesktopManager(){
 const manager=document.getElementById('object-manager');manager.hidden=!objectManagerOpen;
 document.getElementById('desktop-layout').className='desktop-layout'+(objectManagerOpen?' manager-'+installerDisplay.manager_mode:'');
 if(!objectManagerOpen)return;
 manager.replaceChildren();const tools=document.createElement('div');tools.className='manager-tools';const heading=document.createElement('h2');heading.textContent=managerCategory;tools.append(heading);
 const mode=document.createElement('select');mode.id='object-manager-mode';mode.setAttribute('aria-label','Object Manager display');for(const [value,label]of [['split','Split screen'],['full','Full page']]){const option=document.createElement('option');option.value=value;option.textContent=label;mode.append(option);}mode.value=installerDisplay.manager_mode;mode.onchange=()=>{installerDisplay.manager_mode=mode.value;saveDesktopChange();};tools.append(mode);
 const close=displayButton('Close',()=>{objectManagerOpen=false;renderInstallerDisplay();});close.id='close-object-manager';tools.append(close);
 const addApplication=displayButton('Add application',()=>document.getElementById('add-application').showModal());addApplication.id='manager-add-application';tools.append(addApplication);
 const addGroup=displayButton('New taskbar group',()=>{document.getElementById('new-taskbar-group-error').textContent='';document.getElementById('new-taskbar-group-dialog').showModal();});addGroup.id='new-taskbar-group';tools.append(addGroup);
 const search=document.createElement('input');search.type='search';search.placeholder='Find an object';search.setAttribute('aria-label','Find an object');tools.append(search);manager.append(tools);
 const groups=document.createElement('div');groups.className='manager-restored-groups';for(const group of activeDesktopPage().groups){if(!group.visible){const restore=displayButton('Restore '+group.name,()=>{group.visible=true;desktopGroupId=group.id;saveDesktopChange();});restore.dataset.restoreGroup=group.id;groups.append(restore);}}manager.append(groups);
 const collection=document.createElement('div');manager.append(collection);const renderObjects=()=>{
  collection.replaceChildren();const all=managerCategory==='All setup objects',objects=desktopObjects();for(const key of [...activeDesktopPage().desktop,...activeDesktopPage().groups.flatMap(group=>group.objects)])if(!objects.some(object=>object.key===key))objects.push(desktopObject(key));
  const wanted=all?['Applications','Operating systems','Drives']:managerCategory==='Hardware templates'?[]:managerCategory==='Proxmox'||managerCategory==='Settings'?[]:[{'Applications':'Applications','Operating systems':'Operating systems','Drives':'Drives'}[managerCategory]].filter(Boolean);
  for(const type of wanted){const matches=objects.filter(object=>object.type===type&&object.name.toLowerCase().includes(search.value.toLowerCase()));const section=document.createElement('section');section.className='manager-type';const heading=document.createElement('h3');heading.textContent=type==='Drives'?'Drive assignments':type;section.append(heading);if(!matches.length){const empty=document.createElement('p');empty.className='driver-catalog-error';empty.textContent=search.value?'No matching '+type.toLowerCase()+' were found.':'No '+type.toLowerCase()+' objects were discovered.';section.append(empty);}else{const grid=document.createElement('div');grid.className='shortcut-grid';for(const object of matches)grid.append(desktopShortcut(object));section.append(grid);}collection.append(section);}
  if(all||managerCategory==='Drivers'){const section=document.createElement('section');section.className='manager-type';const heading=document.createElement('h3');heading.textContent='Drivers';const driver=document.createElement('button');driver.type='button';driver.className='desktop-shortcut is-disabled';driver.setAttribute('aria-disabled','true');driver.dataset.driverPackage='unavailable';driver.innerHTML='<img src="/installer-icons/rail-hardware.svg" alt=""><span>Universal driver package</span>';driver.title='No verified universal driver package is registered';driver.onclick=()=>openEnvironmentComponent('drivers');const error=document.createElement('p');error.className='driver-catalog-error';error.setAttribute('role','alert');error.textContent='No verified universal driver package is registered. The icon is unavailable for assignment.';section.append(heading,driver,error);collection.append(section);}
  for(const [category,message]of [['Hardware templates','No saved machine hardware templates were discovered.'],['Proxmox','Proxmox host details are summarized in the active environment setup.'],['Settings','Detailed configuration is available from each environment setup block.']])if(all||managerCategory===category){const section=document.createElement('section');section.className='manager-type';const heading=document.createElement('h3');heading.textContent=category;const note=document.createElement('p');note.className='driver-catalog-error';note.textContent=message;section.append(heading,note);collection.append(section);}
 };search.oninput=renderObjects;renderObjects();
}
const renderBaseDisplay=renderInstallerDisplay;
renderInstallerDisplay=function(){
 renderBaseDisplay();const panel=document.getElementById('desktop-page');panel.replaceChildren();
 const tools=document.createElement('div');tools.className='desktop-tools';const manager=displayButton('Object Manager',()=>{objectManagerOpen=!objectManagerOpen;renderInstallerDisplay();});manager.id='desktop-tools-open-object-manager';tools.append(manager);panel.append(tools);
 const bar=document.createElement('div');bar.className='desktop-taskbar';bar.innerHTML='<div id="taskbar-row" hidden><div id="taskbar-scroll"></div><button id="taskbar-edit" type="button" class="taskbar-fixed"><img src="/installer-icons/edit.svg" alt=""><span>Edit</span></button></div><button id="group-corner" type="button" class="taskbar-fixed"></button><div id="taskbar-groups" hidden></div>';panel.append(bar);
 const layout=document.createElement('div');layout.id='desktop-layout';layout.className='desktop-layout';const body=document.createElement('section');body.id='desktop-body';body.innerHTML='<div class="environment-heading"><div><h2></h2><p class="muted environment-draft-status"></p></div><button id="active-environment-settings" type="button"><img src="/installer-icons/rail-settings.svg" alt=""><span>Environment settings</span></button></div><p class="muted">Choose the pieces for this VM or container. Right-click a card to review its settings.</p><div id="active-environment-components" class="environment-components"></div><div id="desktop-body-icons" class="shortcut-grid desktop-body-icons"></div>';body.querySelector('h2').textContent=activeDesktopPage().name;body.querySelector('.environment-draft-status').textContent=(activeDesktopPage().kind==='container'?'Container':'Virtual machine')+' setup draft · not provisioned';body.querySelector('#active-environment-settings').onclick=openEnvironmentSettings;body.querySelector('#active-environment-settings').oncontextmenu=event=>{event.preventDefault();openEnvironmentSettings();};layout.append(body);const objects=document.createElement('aside');objects.id='object-manager';objects.hidden=true;layout.append(objects);panel.append(layout);
 renderEnvironmentComponents();
 for(const key of activeDesktopPage().desktop)document.getElementById('desktop-body-icons').append(desktopShortcut(desktopObject(key)));
 document.getElementById('taskbar-edit').onclick=editDesktopTaskbar;cornerGestures(document.getElementById('group-corner'));renderDesktopTaskbar();renderDesktopManager();
};

function environmentComponentData(page){const objects=desktopObjects();
 const selected=kind=>objects.find(object=>object.kind===kind&&(page.configuration[object.key]?.selected||(kind==='os'&&page.configuration[object.key]?.os===object.id&&page.configuration[object.key]?.variant===object.variant)||(kind==='drive'&&workspaceTarget?.serial===object.id)));
 const assignedApps=page.desktop.map(desktopObject).filter(object=>object.kind==='app');
 return [
  ['drive','Drive assignment',selected('drive')?.name||'Choose an installation drive','/installer-icons/rail-drives.svg',selected('drive')],
  ['platform','Proxmox',selected('drive')?'Target drive selected':'Choose host and install settings','/installer-icons/rail-admin.svg',selected('drive')],
  ['os','Operating system',selected('os')?.name||'Choose an operating system',selected('os')?.icon||'/installer-icons/ubuntu-24.04.svg',selected('os')],
  ['hardware','Hardware profile','No saved machine template discovered','/installer-icons/rail-hardware.svg',null],
  ['drivers','Drivers','No verified universal driver package available','/installer-icons/rail-hardware.svg',null],
  ['app','Applications',assignedApps.length?assignedApps.map(item=>item.name).join(', '):'Choose applications',assignedApps[0]?.icon||'/installer-icons/menu.svg',assignedApps[0]||null]
 ];
}
function renderEnvironmentComponents(){
 const root=document.getElementById('active-environment-components');if(!root)return;root.replaceChildren();const data=environmentComponentData(activeDesktopPage());
 for(const [kind,title,summary,icon]of data){const card=document.createElement('button');card.type='button';card.className='environment-component'+(kind==='drivers'?' is-disabled':'');card.dataset.componentKind=kind;if(kind==='drivers'){card.setAttribute('aria-disabled','true');card.title='No verified universal driver package is available';}card.innerHTML='<img alt=""><span><strong></strong><small></small></span>';card.querySelector('img').replaceWith(shortcutImage(icon));card.querySelector('strong').textContent=title;card.querySelector('small').textContent=summary;card.onclick=()=>openEnvironmentComponent(kind,false);card.oncontextmenu=event=>{event.preventDefault();openEnvironmentComponent(kind,true);};root.append(card);}
}
function openEnvironmentSettings(){
 const page=activeDesktopPage(),dialog=document.getElementById('environment-settings-dialog'),input=document.getElementById('environment-settings-name'),root=document.getElementById('environment-settings-components');
 document.getElementById('environment-settings-title').textContent=page.name+' · Environment settings';document.getElementById('environment-settings-kind').textContent=(page.kind==='container'?'Container':'Virtual machine')+' · setup draft, not provisioned';input.value=page.name;root.replaceChildren();
 for(const [kind,title,summary,icon] of environmentComponentData(page)){const card=document.createElement('button');card.type='button';card.className='environment-component'+(kind==='drivers'?' is-disabled':'');card.dataset.componentKind=kind;if(kind==='drivers'){card.setAttribute('aria-disabled','true');card.title='No verified universal driver package is available';}card.innerHTML='<img alt=""><span><strong></strong><small></small></span>';card.querySelector('img').replaceWith(shortcutImage(icon));card.querySelector('strong').textContent=title;card.querySelector('small').textContent=summary;card.onclick=()=>{dialog.close();openEnvironmentComponent(kind,false);};card.oncontextmenu=event=>{event.preventDefault();dialog.close();openEnvironmentComponent(kind,true);};root.append(card);}
 document.getElementById('environment-settings-status').textContent='Setup draft · not provisioned';dialog.showModal();
}
function openEnvironmentComponent(kind,advanced=true){
 const page=activeDesktopPage(),objects=desktopObjects(),selected=type=>objects.find(object=>object.kind===type&&(page.configuration[object.key]?.selected||(type==='os'&&page.configuration[object.key]?.os===object.id&&page.configuration[object.key]?.variant===object.variant))),assigned=page.desktop.map(desktopObject).find(object=>object.kind==='app');
 const object=kind==='drive'?selected('drive'):kind==='os'?selected('os'):kind==='app'?assigned:null;
 if(!advanced&&({drive:'drives',os:'operating-systems',app:'applications'}[kind])){desktopGroupId={drive:'drives',os:'operating-systems',app:'applications'}[kind];taskbarOpen=true;groupPickerOpen=false;renderInstallerDisplay();return;}
 if(object){showDesktopObjectDetails(object);return;}
 const title={platform:'Proxmox host',hardware:'Hardware profile',drivers:'Drivers',app:'Applications',os:'Operating system',drive:'Drive assignment'}[kind]||kind,dialog=document.getElementById('environment-component-details'),link=document.getElementById('component-detail-link');
 document.getElementById('component-detail-title').textContent=title+' · '+page.name;
 document.getElementById('component-detail-description').textContent=kind==='drivers'?'No verified universal driver package is registered. Driver installation is unavailable until a real package is built and validated.':kind==='hardware'?'No saved machine hardware template was discovered for this environment.':kind==='platform'?'Host options are prepared through the installer plan; no Proxmox host change has been applied.':'Choose an available object from its group on the vertical rail.';
 document.getElementById('component-detail-status').textContent='Advanced configuration stays separate from this overview.';link.hidden=!(kind==='drivers'||kind==='hardware');link.href='/hardware';link.textContent=kind==='drivers'?'Review observed device bindings':'Review hardware inventory';dialog.showModal();
}

function removeDesktopObject(page,key){page.desktop=page.desktop.filter(ref=>ref!==key);for(const group of page.groups){group.objects=group.objects.filter(ref=>ref!==key);if(group.last_object===key)group.last_object=group.objects.at(-1)||null;}}
function placeDesktopObject(page,key,placement){
 if(placement==='desktop'){if(!page.desktop.includes(key))page.desktop.push(key);}
 else if(placement.startsWith('group:')){const group=page.groups.find(group=>group.id===placement.slice(6));if(!group)throw Error('Destination group is no longer available');if(!group.objects.includes(key))group.objects.push(key);group.last_object=key;group.visible=true;}
 else if(placement==='manager')removeDesktopObject(page,key);
 else throw Error('Choose a valid destination');
}
function showDesktopObjectDetails(object){
 const modal=document.getElementById('shortcut-details'),form=document.getElementById('shortcut-settings-form'),fields=document.getElementById('shortcut-settings-fields'),page=activeDesktopPage();fields.replaceChildren();
 document.getElementById('shortcut-detail-name').textContent=object.name;document.getElementById('shortcut-detail-kind').textContent='OBJECT · '+page.name;document.getElementById('shortcut-detail-icon').src=object.icon;document.getElementById('shortcut-settings-status').textContent='';
 document.getElementById('shortcut-detail-description').textContent=object.protected?'This drive is protected and will be preserved. It cannot be selected for installation.':object.unavailable?'This object is absent from current discovery. Its saved placement is retained; configuration and transfer are unavailable.':object.kind==='app'?'Native package: '+object.package+'. Adding it updates the saved Installer build choices; this does not claim installation or runtime verification.':object.kind==='os'?'Selecting this option updates the active Installer build draft; the guest is not provisioned until a reviewed workload build runs.':'Drive serial: '+object.id+'. Selecting it chooses the Installer target; no physical write begins until the reviewed update workflow is confirmed.';
 const config=page.configuration[object.key]||{};
 if(object.kind==='app'&&!object.unavailable){if(object.id==='vscode'){detailField('font','Editor font size',config['editor.fontSize']||14,'number');detailField('theme','Color theme',config['workbench.colorTheme']||'Default Dark Modern');}else if(['spotify','chrome','chatgpt','claude'].includes(object.id)){const scale=detailField('scale','Display scale',config.scale||1,'number');scale.min='.75';scale.max='2';scale.step='.05';if(object.id==='chrome')detailField('homepage','Homepage',config.homepage||'https://www.proxmox.com/','url');}else detailField('arguments','Launch arguments (JSON array)',JSON.stringify(config.arguments||[]));}
 else if(object.kind==='os'&&!object.unavailable){detailField('name','Environment hostname',config.name||page.name);detailField('variant','Variant',object.variant).readOnly=true;}
 const actions=document.createElement('section');actions.className='object-placement-actions';const heading=document.createElement('h3');heading.textContent=object.kind==='drive'?'Drive assignment':'Placement and transfer';actions.append(heading);
 let destination,placement;if(object.kind!=='drive'){const destinationLabel=document.createElement('label');destinationLabel.textContent='Destination VM / container page';destination=document.createElement('select');destination.id='object-destination-page';for(const target of installerDisplay.pages){const option=document.createElement('option');option.value=target.id;option.textContent=target.name;destination.append(option);}destination.value=page.id;destinationLabel.append(destination);actions.append(destinationLabel);
 const placementLabel=document.createElement('label');placementLabel.textContent='Destination placement';placement=document.createElement('select');placement.id='object-destination-placement';placementLabel.append(placement);actions.append(placementLabel);
 const choices=()=>{placement.replaceChildren();for(const [value,name]of [['desktop','Desktop'],['manager','Object Manager only'],...installerDisplay.pages.find(target=>target.id===destination.value).groups.map(group=>['group:'+group.id,'Taskbar: '+group.name])]){const option=document.createElement('option');option.value=value;option.textContent=name;placement.append(option);}};destination.onchange=choices;choices();}
 const transfer=async move=>{try{
  if(object.unavailable)throw Error('Object unavailable; no transfer performed');const target=installerDisplay.pages.find(target=>target.id===destination.value);if(!target)throw Error('Destination page no longer exists');const saved=await readDesktopConfiguration(object,form,page.configuration[object.key]||{});page.configuration[object.key]=structuredClone(saved);
  if(move)removeDesktopObject(page,object.key);
  placeDesktopObject(target,object.key,placement.value);
  if(move&&target.id!==page.id)delete page.configuration[object.key];target.configuration[object.key]=saved;
  renderInstallerDisplay();await persistInstallerDisplay();modal.close();
 }catch(error){document.getElementById('shortcut-settings-status').textContent=error.message;}};
 if(object.kind==='drive'){const select=displayButton(object.protected?'Protected · preserve':'Select installation drive',async()=>{try{await assignDesktopObject(object);modal.close();}catch(error){document.getElementById('shortcut-settings-status').textContent=error.message;}});select.id='select-installation-drive';select.disabled=Boolean(object.protected);actions.append(select);}else{const copy=displayButton('Copy to',()=>transfer(false));copy.id='copy-desktop-object';const move=displayButton('Move to',()=>transfer(true));move.id='move-desktop-object';actions.append(copy,move);}
 const remove=displayButton('Keep in Object Manager only',async()=>{removeDesktopObject(page,object.key);renderInstallerDisplay();try{await persistInstallerDisplay();modal.close();}catch(error){document.getElementById('shortcut-settings-status').textContent=error.message;}});remove.id='unpin-desktop-object';actions.append(remove);
 fields.append(actions);
 form.onsubmit=async event=>{event.preventDefault();try{
  const configuration=await readDesktopConfiguration(object,form,page.configuration[object.key]||{});
  if(object.kind==='app'){const plan=currentWorkspacePlan();if(!plan.applications.apps.includes(object.id))plan.applications.apps.push(object.id);plan.applications.configurations=plan.applications.configurations||{};plan.applications.configurations[object.id]=configuration;await saveWorkspacePlan(plan);}
  if(object.kind==='os'&&!await addShortcutChoice({id:object.id,variant:object.variant,environmentName:configuration.name},'os'))throw Error('Operating system settings were not saved in the Installer plan');
  page.configuration[object.key]=configuration;await persistInstallerDisplay();modal.close();
 }catch(error){document.getElementById('shortcut-settings-status').textContent=error.message;}};
 const advanced=document.createElement('details');advanced.className='advanced-object-settings';advanced.id='shortcut-advanced-settings';const summary=document.createElement('summary');summary.textContent='Advanced settings';advanced.append(summary);for(const child of [...fields.children])if(child!==actions)advanced.append(child);fields.prepend(advanced);modal.showModal();
}
const renderTaskbarDisplay=renderInstallerDisplay;
renderInstallerDisplay=function(){
 renderTaskbarDisplay();
 const form=document.getElementById('new-desktop-page-form');form.onsubmit=async event=>{event.preventDefault();try{if(installerDisplay.pages.length>=64)throw Error('Maximum 64 environment pages');const name=document.getElementById('desktop-page-name').value.trim();if(!name)throw Error('Choose a page name');const kind=document.getElementById('desktop-page-kind').value,id=kind+'-'+Array.from(crypto.getRandomValues(new Uint8Array(16)),value=>value.toString(16).padStart(2,'0')).join('');const page={id,name,kind,desktop:[],groups:newDesktopGroups(),configuration:{}};installerDisplay.pages.push(page);installerDisplay.active_page=id;taskbarOpen=false;renderInstallerDisplay();await persistInstallerDisplay();document.getElementById('new-desktop-page').close();form.reset();}catch(error){document.getElementById('desktop-page-error').textContent=error.message;}};
};

function switchDesktopPage(direction){const index=installerDisplay.pages.findIndex(page=>page.id===installerDisplay.active_page),next=index+direction;if(next<0||next>=installerDisplay.pages.length)return;installerDisplay.active_page=installerDisplay.pages[next].id;taskbarOpen=false;groupPickerOpen=false;saveDesktopChange();}
const renderPageDisplay=renderInstallerDisplay;
renderInstallerDisplay=function(){
 renderPageDisplay();const body=document.getElementById('desktop-body');let start=null;
 body.onpointerdown=event=>{if(event.button!==0||event.target.closest('button,input,select,textarea,a'))return;start={x:event.clientX,y:event.clientY};body.setPointerCapture(event.pointerId);};
 body.onpointerup=event=>{if(!start)return;const dx=event.clientX-start.x,dy=event.clientY-start.y;start=null;if(Math.abs(dx)>=60&&Math.abs(dx)>Math.abs(dy)*1.5)switchDesktopPage(dx<0?1:-1);};body.onpointercancel=()=>{start=null;};
 let touchStart=null;body.ontouchstart=event=>{if(event.touches.length===1)touchStart={x:event.touches[0].clientX,y:event.touches[0].clientY};};body.ontouchend=event=>{if(!touchStart)return;const touch=event.changedTouches[0],dx=touch.clientX-touchStart.x,dy=touch.clientY-touchStart.y;touchStart=null;if(Math.abs(dx)>=60&&Math.abs(dx)>Math.abs(dy)*1.5)switchDesktopPage(dx<0?1:-1);};
};

async function readDesktopConfiguration(object,form,current){
 if(object.unavailable)throw Error('Object unavailable; configuration not saved');const values=new FormData(form);
 if(object.kind==='app'){let configuration=object.id==='vscode'?{'editor.fontSize':Number(values.get('font')),'workbench.colorTheme':values.get('theme')}:values.has('scale')?{scale:Number(values.get('scale'))}:{arguments:JSON.parse(values.get('arguments'))};if(values.has('homepage'))configuration.homepage=values.get('homepage');const result=await updatePost('/install-plan/app-config',{app:object.id,configuration});return result.configuration;}
 if(object.kind==='os'){const name=values.get('name').trim();if(!name||name.length>80)throw Error('Choose an environment name of at most 80 characters');return {os:object.id,variant:object.variant,name,selected:true};}
 return structuredClone(current);
}

function installerObjectDrop(node,placement){
 node.ondragover=event=>{if(!event.dataTransfer.types.includes('application/x-baseline-desktop-object'))return;event.preventDefault();node.classList.add('drag-over');};
 node.ondragleave=()=>node.classList.remove('drag-over');
 node.ondrop=async event=>{event.preventDefault();event.stopPropagation();node.classList.remove('drag-over');try{const key=event.dataTransfer.getData('application/x-baseline-desktop-object'),object=desktopObject(key);if(object.unavailable)throw Error('Object is no longer available');placeDesktopObject(activeDesktopPage(),key,placement());await saveDesktopChange();}catch(error){document.getElementById('display-save-status').textContent='Object placement failed: '+error.message;}};
}
const renderGestureDisplay=renderInstallerDisplay;
renderInstallerDisplay=function(){
 renderGestureDisplay();if(!installerDisplay)return;const rail=document.getElementById('desktop-left-rail'),groups=document.getElementById('rail-object-groups'),switcher=document.getElementById('environment-switcher');
 if(!document.getElementById('environment-switcher-select')){const select=document.createElement('select');select.id='environment-switcher-select';select.setAttribute('aria-label','Active VM or container');select.onchange=async()=>{installerDisplay.active_page=select.value;renderInstallerDisplay();await persistInstallerDisplay();};switcher.append(select);}
 const select=document.getElementById('environment-switcher-select');select.replaceChildren();for(const env of installerDisplay.pages){const option=document.createElement('option');option.value=env.id;option.textContent=env.name;select.append(option);}select.value=installerDisplay.active_page;
 groups.replaceChildren();const categoryMap=[['Applications','applications','/installer-icons/menu.svg'],['Operating system','operating-systems','/installer-icons/ubuntu-24.04.svg'],['Drive assignment','drives','/installer-icons/rail-drives.svg'],['Proxmox','proxmox','/installer-icons/rail-admin.svg'],['Hardware','hardware','/installer-icons/rail-hardware.svg'],['Drivers','drivers','/installer-icons/rail-hardware.svg'],['Advanced','settings','/installer-icons/rail-settings.svg']];
 for(const [label,id,icon]of categoryMap){const button=document.createElement('button');button.type='button';button.dataset.railGroup=id;button.setAttribute('aria-pressed',String(desktopGroupId===id));button.innerHTML='<img alt=""><span></span>';button.querySelector('img').replaceWith(shortcutImage(icon));button.querySelector('span').textContent=label;button.onclick=()=>{desktopGroupId=id;const managerTypes={applications:'Applications','operating-systems':'Operating systems',drives:'Drives',drivers:'Drivers',hardware:'Hardware templates',proxmox:'Proxmox',settings:'Settings'};managerCategory=managerTypes[id];taskbarOpen=true;renderInstallerDisplay();};groups.append(button);}
 const addEnvironment=displayButton('Add VM or container',()=>{document.getElementById('desktop-page-error').textContent='';document.getElementById('new-desktop-page').showModal();});addEnvironment.id='add-desktop-page';addEnvironment.innerHTML='<img src="/installer-icons/edit.svg" alt=""><span>New VM</span>';groups.append(addEnvironment);
 const objectManager=displayButton('Object Manager',()=>{managerCategory='All setup objects';objectManagerOpen=true;renderInstallerDisplay();});objectManager.id='open-object-manager';objectManager.innerHTML='<img src="/installer-icons/menu.svg" alt=""><span>Objects</span>';groups.append(objectManager);
 installerObjectDrop(document.getElementById('desktop-body-icons'),()=> 'desktop');installerObjectDrop(document.getElementById('taskbar-scroll'),()=>{const group=activeTaskbarGroup();if(!group)throw Error('Choose a taskbar group first');return 'group:'+group.id;});
};

document.getElementById('new-taskbar-group-form').onsubmit=async event=>{event.preventDefault();try{const page=activeDesktopPage();if(page.groups.length>=64)throw Error('Maximum 64 groups per page');const name=document.getElementById('new-taskbar-group-name').value.trim();if(!name)throw Error('Choose a group title');const id='group-'+Array.from(crypto.getRandomValues(new Uint8Array(16)),value=>value.toString(16).padStart(2,'0')).join('');page.groups.push({id,name,objects:[],visible:true,last_object:null});desktopGroupId=id;renderInstallerDisplay();await persistInstallerDisplay();document.getElementById('new-taskbar-group-dialog').close();event.target.reset();}catch(error){document.getElementById('new-taskbar-group-error').textContent=error.message;}};
document.getElementById('environment-settings-form').onsubmit=async event=>{event.preventDefault();const page=activeDesktopPage(),input=document.getElementById('environment-settings-name'),name=input.value.trim();try{if(!name||name.length>80)throw Error('Choose a VM or container name of at most 80 characters');if(installerDisplay.pages.some(other=>other.id!==page.id&&other.name.trim().toLowerCase()===name.toLowerCase()))throw Error('That VM or container name is already in use');page.name=name;await persistInstallerDisplay();renderInstallerDisplay();document.getElementById('environment-settings-dialog').close();}catch(error){document.getElementById('environment-settings-status').textContent='Name was not saved: '+error.message;}};
'''.encode()
