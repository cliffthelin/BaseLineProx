"""Hardware configuration categories and associations to the real installer catalog."""
import html
from urllib.parse import quote
import hardware_inventory
import installer_cache

# Associations describe purpose, not a claim of hardware compatibility.
PACKAGE_IDS = {
    'drives': ('nvme-cli', 'smartmontools'),
    'network': ('ethtool', 'iperf3', 'firmware-mediatek', 'firmware-realtek'),
    'system': ('lm-sensors', 'amd64-microcode', 'intel-microcode', 'inxi'),
}


def package_state(runner):
    if runner is None:
        return {'available':False,'error':'No package observation runner configured'}
    try:
        result = runner.run(['dpkg-query','-W','-f=${binary:Package}\t${Version}\t${db:Status-Status}\n'], timeout=20)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'dpkg-query failed')
        installed = {}
        for line in result.stdout.splitlines():
            fields = line.split('\t')
            if len(fields) != 3:
                raise RuntimeError('Malformed native package database result')
            name, version, state = fields
            if state == 'installed':
                installed[name.split(':',1)[0]] = version
        return {'available':True,'installed':installed}
    except Exception as exc:
        return {'available':False,'error':str(exc)}


def _packages(ids, state):
    catalog = {entry.entry_id:entry for entry in installer_cache.catalog()}
    entries = [catalog[name] for name in ids if name in catalog]
    if not entries:
        return '<p>No installer package association is declared for this category. Installed kernel drivers are listed with their devices.</p>'
    notice = '' if state.get('available') else '<p role="alert">Package observation unavailable: '+html.escape(state.get('error','Unknown observation failure'))+'</p>'
    rows = []
    for entry in entries:
        version = state.get('installed',{}).get(entry.entry_id)
        status = ('Installed '+version if version else 'Not installed') if state.get('available') else 'Unknown'
        rows.append('<tr><td>'+html.escape(entry.name)+'</td><td>'+html.escape(status)+'</td><td>'+html.escape(entry.notes)+
                    '</td><td><a href="/installer-cache#cache-entry-'+quote(entry.entry_id,safe='')+'">Installer and source</a></td></tr>')
    return notice+'<p>Catalog associations describe purpose. Select firmware for the actual vendor; these are not automatic compatibility recommendations.</p><table class="hw-table"><thead><tr><th>Package</th><th>Installed state</th><th>Purpose</th><th>Installer Cache</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table>'


def render(inventory, *, configuration_html, driver_sections, packages, render_inventory, target=''):
    groups = hardware_inventory.group_pci(inventory.get('pci') or [])
    def devices(labels, **buses):
        pci = [device for label in labels for device in groups.get(label,[])]
        return render_inventory({'pci':pci,**buses}) + ''.join(driver_sections.get(label,'') for label in labels)
    drives_link = ('<p><a href="/vms">Configure this VM’s virtual disks</a>. Guest disks do not identify host drives.</p>' if target else
                   '<p><a href="/drive-admin">Drive Administration</a> manages enrollment, storage roles and rebuild actions. Choose a drive below to open it by serial.</p>')
    panels = [
        ('configuration','Configuration',configuration_html),
        ('drives','Drives',drives_link+devices(['Storage'],block=inventory.get('block',[]))+_packages(PACKAGE_IDS['drives'],packages)),
        ('network','Network',devices(['Network'],net=inventory.get('net',[]))+_packages(PACKAGE_IDS['network'],packages)),
        ('graphics','Graphics',devices(['Graphics'])+_packages((),packages)),
        ('usb','USB',devices(['USB Controllers'],usb=inventory.get('usb',[]))+_packages((),packages)),
        ('audio','Audio',devices(['Audio'])+_packages((),packages)),
        ('system','System and other',devices(['System / Bridges','Other'])+_packages(PACKAGE_IDS['system'],packages)),
        ('packages','Packages and firmware',_packages(tuple(dict.fromkeys(name for ids in PACKAGE_IDS.values() for name in ids)),packages)),
    ]
    errors = ''.join('<p role="alert">'+html.escape(item['bus'])+': '+html.escape(item['error'])+'</p>' for item in inventory.get('errors',[]))
    buttons = ''.join(f'<button type="button" role="tab" id="hardware-tab-{key}" aria-controls="hardware-panel-{key}" aria-selected="{"true" if index==0 else "false"}" tabindex="{0 if index==0 else -1}" data-hardware-tab="{key}">{title}</button>' for index,(key,title,_) in enumerate(panels))
    contents = ''.join(f'<section role="tabpanel" id="hardware-panel-{key}" aria-labelledby="hardware-tab-{key}" {"hidden" if index else ""}>{body}</section>' for index,(key,_,body) in enumerate(panels))
    return errors+'<style>[role="tabpanel"][hidden]{display:none!important}.hardware-tabs{display:flex;flex-wrap:wrap;gap:.4rem;margin:1rem 0}.hardware-tabs [aria-selected="true"]{outline:2px solid #8badf4}</style><div class="hardware-tabs" role="tablist" aria-label="Hardware categories">'+buttons+'</div>'+contents+'''<script>
(()=>{const tabs=[...document.querySelectorAll('[data-hardware-tab]')];
function select(tab){for(const item of tabs){const active=item===tab;item.setAttribute('aria-selected',String(active));item.tabIndex=active?0:-1;document.getElementById(item.getAttribute('aria-controls')).hidden=!active;}history.replaceState(null,'','#hardware-'+tab.dataset.hardwareTab);}
for(const tab of tabs){tab.onclick=()=>select(tab);tab.onkeydown=event=>{let index=tabs.indexOf(tab);if(event.key==='ArrowRight')index=(index+1)%tabs.length;else if(event.key==='ArrowLeft')index=(index+tabs.length-1)%tabs.length;else if(event.key==='Home')index=0;else if(event.key==='End')index=tabs.length-1;else return;event.preventDefault();select(tabs[index]);tabs[index].focus();};}
const requested=tabs.find(tab=>'#hardware-'+tab.dataset.hardwareTab===location.hash);if(requested)select(requested);
})();</script>'''
