"""Combined current configuration, using each owner's existing edit routes."""
import html
import settings_web as sw
import structured_controls


def _table(value, prefix=''):
    rows = []
    if isinstance(value, dict):
        items = value.items()
    elif isinstance(value, (list, tuple)):
        items = enumerate(value)
    else:
        items = [(prefix or 'Value', value)]
        prefix = ''
    for key, item in items:
        path = f'{prefix}.{key}' if prefix else str(key)
        if isinstance(item, (dict, list, tuple)):
            rows.append(_table(item, path))
        else:
            rows.append(f'<tr><th>{html.escape(path)}</th><td>{html.escape(str(item))}</td></tr>')
    return ''.join(rows)


def render(settings, admin, *, elevated=False, additional=(), errors=()):
    sections = []
    def add(title, link, content):
        sections.append(f'<section data-config-section data-owner="{html.escape(title, quote=True)}">'
                        f'<h2>{html.escape(title)}</h2><a href="{html.escape(link, quote=True)}">Open owning tab</a>{content}</section>')
    for group, values in settings.items():
        if not group.startswith('_'):
            current = {group: values}
            if '_live_interfaces' in settings:
                current['_live_interfaces'] = settings['_live_interfaces']
            add('Settings / ' + group, '/settings', sw.render_configuration_sections(current))
    # Reuse the complete admin controls, including the real elevation gate.
    admin_page = sw.render_admin_page(admin, elevated=elevated).decode()
    admin_body = admin_page.split('<body>', 1)[1].split('</body>', 1)[0]
    admin_body = admin_body.replace(structured_controls.script(), '').replace('<h1>Baseline settings</h1>', '')
    add('Admin', '/admin', admin_body)
    for title, link, value in additional:
        add(title, link, '<p>Current configuration. Change it in the owning tab.</p>'
            '<table>' + _table(value) + '</table>' if value else '<p>No stored entries.</p>')
    options = ''.join(f'<option>{html.escape(title)}</option>' for title in
                     ['Settings / ' + k for k in settings if not k.startswith('_')] + ['Admin'] + [a[0] for a in additional])
    notices = ''.join(f'<p role="alert">{html.escape(error)}</p>' for error in errors)
    page = sw._html('Master Config', '''<p>Current configuration from the owning tabs. Editable settings save automatically; Admin settings require elevation.</p>
<label>Search <input type="search" id="config-search" placeholder="Setting, value or section"></label>
<label>Section <select id="config-filter"><option value="">All sections</option>''' + options + '''</select></label>
<p id="config-match-count" role="status"></p>''' + notices + ''.join(sections) + '''
<script>
(()=>{const search=document.getElementById('config-search'),filter=document.getElementById('config-filter');
const sections=[...document.querySelectorAll('[data-config-section]')];
function apply(){const query=search.value.toLowerCase().trim();let count=0;
for(const section of sections){const values=[...section.querySelectorAll('input,select,textarea')].map(i=>i.value).join(' ');
section.hidden=!!((filter.value&&section.dataset.owner!==filter.value)||(query&&!(section.textContent+' '+values).toLowerCase().includes(query)));if(!section.hidden)count++;}
document.getElementById('config-match-count').textContent=count+' sections shown';}
search.addEventListener('input',apply);filter.addEventListener('change',apply);apply();})();
</script>''')

    return page.replace(b'<h1>Baseline settings</h1>', b'<h1>Master Config</h1>')
