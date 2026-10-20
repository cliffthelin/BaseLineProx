"""Read-only installed-system readiness; observations never prove cold boot."""
import html
import network
import lan_firewall
import storage_policy
from firstboot_network_repair import facts_verification

SERVICES=('baseline-storage-verify.service','baseline-persist-bind-mounts.service','baseline-storage-reconcile.service',
          'baseline-firstboot.service','baseline.service','baseline-web.service','baseline-kiosk.service',
          'pve-cluster.service','pvedaemon.service','pveproxy.service')


def collect(runner, *, network_check=None):
    checks=[]
    try:
        storage=storage_policy.verify_runtime(runner)
        ready=isinstance(storage,dict) and storage.get('state')=='storage_verified'
        checks.append({'id':'storage','ready':ready,'detail':
            'Mounted storage identities, restrictions and capacity verified' if ready else 'Storage verification result unavailable'})
    except Exception as exc:
        checks.append({'id':'storage','ready':False,'detail':str(exc)})
    try:
        facts=(network_check or network.check_lifeline)()
        verified=facts_verification(facts)
        checks.append({'id':'network','ready':all(verified.values()),
                       'detail':'Address and gateway checks: '+str(verified),'facts':facts})
    except Exception as exc:
        checks.append({'id':'network','ready':False,'detail':str(exc)})
    try:
        # An address and a reachable router do not establish internet access.
        # Probe HTTPS from this installed system with normal certificate checks,
        # without silently inheriting a developer's proxy.
        observed=runner.run(['curl','--noproxy','*','--proto','=https','--proto-redir','=https',
            '--location','--max-redirs','3','--connect-timeout','5','--max-time','15',
            '--fail','--silent','--show-error','--output','/dev/null','--write-out','%{http_code}',
            'https://www.proxmox.com/'],timeout=20)
        code=observed.stdout.strip()
        ready=observed.returncode==0 and len(code)==3 and code.isdigit() and 200<=int(code)<300
        checks.append({'id':'internet','ready':ready,'detail':
            'DNS and certificate-verified HTTPS to www.proxmox.com succeeded' if ready else
            'Direct HTTPS internet probe failed or returned an unexpected status'})
    except Exception as exc:
        checks.append({'id':'internet','ready':False,'detail':str(exc)})
    active,detail=lan_firewall.verify_active(runner)
    checks.append({'id':'firewall','ready':active is True,'detail':detail})
    for unit in SERVICES:
        try:
            observed=runner.run(['systemctl','is-active','--',unit],timeout=10)
            state=observed.stdout.strip()
            checks.append({'id':unit,'ready':observed.returncode==0 and state=='active',
                'detail':state or observed.stderr.strip() or 'Service status unavailable'})
        except Exception as exc:
            checks.append({'id':unit,'ready':False,'detail':str(exc)})
    return {'format':'baseline.installation-readiness/v1','ready':all(row['ready'] for row in checks),
            'checks':checks,'cold_boot_verified':False}


def render(report):
    rows=''.join('<tr><td>'+html.escape(row['id'])+'</td><td>'+('Ready' if row['ready'] else 'Blocked')+
        '</td><td>'+html.escape(row['detail'])+'</td></tr>' for row in report['checks'])
    return ('<h1>Installation readiness</h1><p>'+('Required checks passed.' if report['ready'] else 'Required checks have not passed.')+
            ' This report does not verify a native cold boot.</p><table><thead><tr><th>Check</th><th>Status</th><th>Observation</th></tr></thead><tbody>'+
            rows+'</tbody></table><p><a href="/installation-readiness">Refresh observations</a> · '
            '<a href="/install-plan">Installer Plan</a></p>')
