#!/usr/bin/env python3
"""Real Chromium and encrypted filesystem, synthetic credentials/drive discovery."""
from pathlib import Path
import json
import sys
import tempfile
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'unit'), str(Path(__file__).resolve().parents[2] / 'baseline/lib')]
from playwright.sync_api import sync_playwright, expect
from test_baseline_web import _RealServerCase, _base_deps
from test_install_plan import discover, proxmox_disk, baseline_disk
from configuration_drafts import DraftStore
import vault

with tempfile.TemporaryDirectory(prefix='baseline-ai-browser-') as work:
    root = Path(work)
    store = vault.Vault(root / 'vault')
    store.set_passphrase('synthetic browser passphrase')
    drafts = DraftStore(root / 'drafts.sqlite')
    case = _RealServerCase(_base_deps(draft_store=drafts, vault_roots=[('USER_ADMIN', 'admin', str(root / 'vault'))],
        vault_passphrase='synthetic browser passphrase', ai_parent_home=root / 'parent', ai_parent_environ={},
        install_plan_discovery=lambda: discover(proxmox_disk(), baseline_disk())))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1280, 'height': 1000})
            context.add_cookies([{'name': 'session', 'value': case.token, 'url': f'http://127.0.0.1:{case.port}'}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{case.port}/ai-setup/installer')
            expect(page.locator('#ai-status')).to_contain_text('No prepared profile')
            expect(page.locator('[name=provider]')).to_have_count(14)
            page.locator('#ai-mode').select_option('custom')
            page.locator('[name=target][value="baseline"]').check()
            page.locator('#custom-provider').select_option('openai')
            page.locator('#custom-api-key').fill('synthetic-browser-key')
            page.locator('#add-custom').click()
            page.locator('#ai-save').click()
            expect(page.locator('#ai-status')).to_contain_text('AI setup saved')
            assert 'synthetic-browser-key' not in json.dumps(drafts.get('root', 'installer'))
            assert 'synthetic-browser-key' not in (root / 'vault/AI_SETUP_DEFAULT').read_text()
            page.reload()
            expect(page.locator('#ai-status')).to_contain_text('Encrypted profile prepared')
            expect(page.locator('[name=provider][value=openai]')).to_be_checked()
            expect(page.locator('[name=target][value=baseline]')).to_be_checked()
            assert page.locator('#custom-env').input_value() == ''
            page.screenshot(path='/tmp/baseline-ai-installer.png', full_page=True)
            page.locator('#ai-mode').select_option('none')
            page.locator('#ai-save').click()
            expect(page.locator('#ai-status')).to_contain_text('AI setup saved')
            assert drafts.get('root', 'installer')['document']['host_configuration']['ai_setup']['mode'] == 'none'
            assert not errors, errors
            browser.close()
        print('PASS: all 14 catalog entries; custom encrypted save; references-only draft; reload; opt-out; synthetic credentials only')
    finally:
        case.close()
