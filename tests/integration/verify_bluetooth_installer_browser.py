#!/usr/bin/env python3
"""Real Chromium opt-in persistence with synthetic drives; no hardware transfer."""
from pathlib import Path
import sys
import tempfile
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'unit'), str(Path(__file__).resolve().parents[2] / 'baseline/lib')]
from playwright.sync_api import sync_playwright, expect
from test_baseline_web import _RealServerCase, _base_deps
from test_install_plan import discover, proxmox_disk, baseline_disk
from configuration_drafts import DraftStore

with tempfile.TemporaryDirectory(prefix='baseline-bt-browser-') as work:
    store = DraftStore(Path(work) / 'drafts.sqlite')
    case = _RealServerCase(_base_deps(draft_store=store,
        install_plan_discovery=lambda: discover(proxmox_disk(), baseline_disk())))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1400, 'height': 1000})
            context.add_cookies([{'name': 'session', 'value': case.token, 'url': f'http://127.0.0.1:{case.port}'}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            url = f'http://127.0.0.1:{case.port}/install-plan?display=desktop'
            page.goto(url)
            page.wait_for_function('workspaceCatalog !== null')
            page.locator('#parent-configuration-open').click()
            choice = page.locator('#bluetooth-from-parent')
            expect(choice).to_be_visible()
            expect(choice).not_to_be_checked()
            choice.check()
            expect(page.locator('#bluetooth-choice-status')).to_contain_text('Saved')
            assert store.get('root', 'installer')['document']['host_configuration']['bluetooth_from_parent'] is True
            page.reload()
            page.wait_for_function('workspaceCatalog !== null')
            page.locator('#parent-configuration-open').click()
            expect(choice).to_be_checked()
            page.screenshot(path='/tmp/baseline-bluetooth-installer.png')
            choice.uncheck()
            expect(page.locator('#bluetooth-choice-status')).to_contain_text('Saved')
            assert store.get('root', 'installer')['document']['host_configuration']['bluetooth_from_parent'] is False
            page.goto(url.replace('desktop', 'workspace'))
            page.wait_for_function('workspaceCatalog !== null')
            page.locator('#parent-configuration-open').click()
            expect(choice).to_be_visible()
            expect(choice).not_to_be_checked()
            assert not errors, errors
            browser.close()
        print('PASS: desktop/workspace option, opt-in, saved reload, opt-out; synthetic drives only')
    finally:
        case.close()
