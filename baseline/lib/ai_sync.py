"""Retry opted-in AI delivery to running managed guests after vault unlock."""
import json
import os
from pathlib import Path
import time

import ai_provisioning as ai
import ai_runtime
import vault


def deliver(config, profile, targets, push):
    report = {'delivered': [], 'pending': {}, 'authenticated': False}
    for target in targets:
        if not ai.permitted(config, 'kasm:server' if target == 'kasm' else target):
            continue
        try:
            push(target, ai.selected_profile(profile, config))
            report['delivered'].append(target)
        except Exception:
            report['pending'][target] = 'delivery unavailable; check running target, managed identity, Python and guest owner'
    return report


def run(*, config_path='/mnt/USER_ADMIN/ai-setup.json', runtime=vault.RUNTIME_DIR, deps=None):
    import baseline_web as web
    config_file = Path(config_path)
    if not config_file.exists():
        return {'state': 'not requested'}
    config = ai.choice({'host_configuration': {'ai_setup': json.loads(config_file.read_text())}})
    if config['mode'] == 'none':
        __import__('shutil').rmtree(ai_runtime.RUNTIME, ignore_errors=True)
        return {'state': 'not requested'}
    unlocked = Path(runtime) / config['profile']
    if not unlocked.is_file() or unlocked.is_symlink() or unlocked.stat().st_mode & 0o077:
        return {'state': 'locked', 'message': 'unlock USER_ADMIN vault to activate AI setup'}
    profile = ai.validate_profile(json.loads(unlocked.read_text()))
    deps = deps or {}
    targets = [t for t in ('substrate', 'baseline') if ai.permitted(config, t)]
    errors = {}
    if any(t.startswith('vm:') for t in config['targets']):
        try:
            targets += ['vm:' + vm['name'] for vm in web._vm_host_for(deps).list_vms() if vm.get('running')]
        except Exception:
            errors['vms'] = 'managed VM inventory unavailable'
    if any(t.startswith('ct:') for t in config['targets']):
        try:
            host = web._container_host_for(deps)
            if host is None:
                raise OSError('native containers unavailable')
            targets += ['ct:' + ct['name'] for ct in host.list_containers() if ct.get('running')]
        except Exception:
            errors['containers'] = 'managed container inventory unavailable'
    if any(t.startswith('kasm:') for t in config['targets']):
        targets.append('kasm')
        try:
            listing_script = "import json,subprocess; ids=subprocess.check_output(['docker','ps','-q'],text=True).split(); rows=json.loads(subprocess.check_output(['docker','inspect',*ids],text=True)) if ids else []; print(json.dumps([r['Id'] for r in rows if 'HOME=/home/kasm-user' in r.get('Config',{}).get('Env',[])]))"
            response = web._vault_push_for(deps, 'kasm')(['python3', '-c', listing_script], b'')
            ids = json.loads(response.get('out-data') or '')
            if not isinstance(ids, list) or any(not isinstance(i, str) or not __import__('re').fullmatch('[a-f0-9]{12,64}', i) for i in ids):
                raise ValueError('invalid Kasm inventory')
            targets += ['kasm:' + ident for ident in ids]
        except Exception:
            errors['kasm'] = 'Kasm workspace inventory unavailable'
    def push(target, selected):
        if target in ('substrate', 'baseline'):
            ai_runtime.install(selected, account='root', source=Path(ai_runtime.__file__).read_text(), launcher='/opt/baseline/bin/baseline-ai-run',
                history_root='/mnt/APPDATA_ADMIN/claude-code/.claude' if config.get('claude_history') else None)
        else:
            argv, data = ai.delivery(selected, account='root' if target == 'kasm' else None)
            web._vault_push_for(deps, target)(argv, data)
    report = deliver(config, profile, targets, push)
    report.update(state='pending' if errors or report['pending'] else 'delivered', inventory_errors=errors, checked=time.time())
    return report


def main():
    from write_once import write_if_changed
    try:
        report = run()
    except Exception:
        report = {'state': 'error', 'message': 'AI setup sync failed; inspect configured profile and native target availability'}
    if Path('/mnt/USER_ADMIN/ai-setup.json').is_file():
        write_if_changed('/mnt/USER_ADMIN/ai-setup-status.json', json.dumps(report) + '\n', mode=0o600)
    print(json.dumps(report))
    return 1 if report.get('state') in ('error', 'pending') else 0
