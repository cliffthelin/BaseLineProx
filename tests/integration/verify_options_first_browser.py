"""Real Chromium UI checks against isolated test HTTP/configuration fixtures.

Run with a Python environment containing Playwright and installed Chromium.
These are browser tests, not physical hardware or production apply evidence.
"""
import http.server
import json
from pathlib import Path
import sys
import threading
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'baseline/lib'))
import settings_web
import install_plan_page
import recipe_page
import master_configuration
import baseline_web
import hardware_tabs
import installer_cache
from hardware_inventory import BlockDevice, NetInterface
import install_plan
from configuration_drafts import DraftStore, DraftConflict
from playwright.sync_api import sync_playwright

state = {'smartd_auto_offline': 'on', 'ethtool_duplex': 'full', 'ethtool_speed': '',
         'smartd_selftest_schedule': '', 'smartd_email': '',
         'nested': {'enabled': True, 'count': 2, 'items': []}}
requests = []


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith('/workloads/job?') or self.path.startswith('/install-plan/input-bundle?'):
            value={'state':'completed','result':{'message':'Test fixture source acquisition completed'}} if self.path.startswith('/workloads') else {'ready':False,'executed':False,'errors':['Missing publisher source lock: proxmox_iso']}
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(value).encode());return
        if self.path in ('/install-plan/draft', '/recipes/draft'):
            kind = 'installer' if self.path.startswith('/install-plan') else 'recipe'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'ok':True,'draft':drafts.get('test-user',kind)}).encode())
            return
        if self.path.startswith('/drive-admin?'):
            from urllib.parse import parse_qs, urlparse
            serial=parse_qs(urlparse(self.path).query)['serial'][0]
            body=baseline_web.render_drive_admin_page(drives=[{'path':'/dev/sdb','serial':'default-drive','model':'default','is_default':True}, {'path':'/dev/sdc','serial':'hardware-drive','model':'linked'}],volumes=[],actions=[],selected_serial=serial)
            self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(body);return
        pages = {
            '/installer-cache': lambda: baseline_web.render_installer_cache_page(installer_cache.CacheReport(root='/test-cache',mounted=False,mount_detail='Test fixture mount unavailable')),
            '/settings': lambda: settings_web.render_settings_page({'proxmox': state}),
            '/admin': lambda: settings_web.render_admin_page({'sessions': {'default_session_ttl_hours': 24}}, elevated=False),
            '/hardware': lambda: baseline_web._with_nav(baseline_web.render_hardware_page(dependency_results=[],category_html=hardware_tabs.render(
                {'block':[BlockDevice('sdc',serial='hardware-drive')],'net':[NetInterface('eth-test','UP')]},configuration_html='<p>Current configuration</p>',driver_sections={},
                packages={'available':True,'installed':{'ethtool':'6.0'}},render_inventory=baseline_web._render_inventory)), '/hardware'),
            '/plan': install_plan_page.render,
            '/recipes': recipe_page.render,
            '/master': lambda: master_configuration.render({'diagnostics': {'ethtool_duplex': 'full'}}, {'sessions': {'default_session_ttl_hours': 24}}, additional=[('Operations', '/operations', {'interval_hours': 48})]),
        }
        body = pages[self.path]()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        requests.append(body)
        if self.path=='/host/restart':
            self.send_response(401);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps({'error':'not authenticated'}).encode());return
        if self.path in ('/install-plan/draft', '/recipes/draft'):
            kind = 'installer' if self.path.startswith('/install-plan') else 'recipe'
            try:
                result = {'ok':True,'draft':drafts.save('test-user',kind,body['document'],expected_revision=body['revision'])}
            except DraftConflict as exc:
                self.send_response(409)
                self.send_header('Content-Type','application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok':False,'message':str(exc)}).encode())
                return
        elif self.path == '/installer-cache/acquire':
            assert body['source']=='ubuntu_base' and isinstance(body['request_id'],str)
            result={'job_id':'browser-source-fixture','state':'queued','executed':False}
        elif self.path == '/install-plan/prepare-inputs':
            assert body['revision']==drafts.get('test-user','installer')['revision']
            result={'job_id':'browser-fixture-job','state':'queued','executed':False}
        elif self.path == '/install-plan/action':
            result = install_plan_page.perform(body, discovery_provider=lambda: {'drives': [], 'unenrolled': []})
        else:
            state.update(body)
            result = {'outcome': 'applied', 'detail': 'Saved test configuration'}
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())


def main():
    global drafts
    temporary = tempfile.TemporaryDirectory(prefix='baseline-browser-drafts-')
    drafts = DraftStore(Path(temporary.name) / 'drafts.sqlite')
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            base = f'http://127.0.0.1:{server.server_port}'
            page.goto(base + '/settings')
            assert page.locator('textarea:visible').count() == 0
            page.locator('select[name=ethtool_duplex]').select_option('half')
            page.wait_for_function("document.querySelector('[data-save-status]').textContent.includes('Saved')")
            assert state['ethtool_duplex'] == 'half'
            assert state['nested'] == {'enabled': True, 'count': 2, 'items': []}
            page.get_by_label('count', exact=True).fill('3')
            page.get_by_label('count', exact=True).press('Tab')
            page.wait_for_function("document.querySelector('input[name=nested]').value.includes('3')")
            page.wait_for_timeout(650)
            assert state['nested']['count'] == 3
            number_width = page.get_by_label('count', exact=True).bounding_box()['width']
            assert number_width < 140, number_width
            page.locator('details.field-info').first.locator('summary').click()
            assert page.locator('details.field-info').first.locator('p').is_visible()
            page.get_by_text('Advanced custom value', exact=True).first.click()
            page.get_by_text('Override selection', exact=True).first.locator('input').check()
            assert page.locator('select[name=ethtool_speed]').is_disabled()
            page.goto(base + '/admin')
            assert page.locator('button', has_text='Save').count() == 0
            assert page.locator('input[type=number]').is_disabled()
            page.goto(base + '/plan')
            page.get_by_role('button', name='Discover and autofill').click()
            page.get_by_label('variant', exact=True).select_option('server')
            assert page.locator('textarea:visible').count() == 0
            assert json.loads(page.locator('#plan').input_value())['environment']['variant'] == 'server'
            page.wait_for_function("document.getElementById('draft-status').textContent.includes('Saved')")
            page.reload()
            page.wait_for_function("document.getElementById('draft-status').textContent.includes('Restored')")
            assert page.get_by_label('variant', exact=True).input_value() == 'server'
            page.get_by_role('button',name='Prepare installation inputs').click()
            page.wait_for_function("document.getElementById('input-status').textContent.includes('Installation blocked')")
            assert page.locator('#input-errors').inner_text()=='Missing publisher source lock: proxmox_iso'
            assert any('request_id' in request for request in requests)
            page.goto(base + '/recipes')
            page.locator('#recipe-template').select_option('ubuntu-server')
            assert page.get_by_label('locale', exact=True).is_visible()
            assert json.loads(page.locator('#document').input_value())['source']['sha256'] == ''
            assert page.locator('textarea:visible').count() == 0
            page.wait_for_function("document.getElementById('draft-status').textContent.includes('Saved')")
            page.reload()
            page.wait_for_function("document.getElementById('draft-status').textContent.includes('Restored')")
            assert json.loads(page.locator('#document').input_value())['id'] == 'ubuntu-server'
            other = browser.new_page()
            other.goto(base + '/recipes')
            other.wait_for_function("document.getElementById('draft-status').textContent.includes('Restored')")
            page.locator('#recipe-template').select_option('chromium')
            page.wait_for_function("document.getElementById('draft-status').textContent.includes('Saved')")
            other.locator('#recipe-template').select_option('ubuntu-desktop')
            other.wait_for_function("document.getElementById('draft-status').textContent.includes('another editor')")
            assert drafts.get('test-user','recipe')['document']['document']['id'] == 'chromium'
            other.get_by_role('button', name='Reload saved draft (discard local edits)').click()
            other.wait_for_function("document.getElementById('draft-status').textContent.includes('Restored')")
            assert json.loads(other.locator('#document').input_value())['id'] == 'chromium'
            other.close()
            page.goto(base + '/master')
            assert page.locator('[data-config-section]:visible').count() == 3
            page.locator('#config-search').fill('interval_hours')
            assert page.locator('[data-config-section]:visible').count() == 1
            page.locator('#config-search').fill('')
            page.locator('#config-filter').select_option('Admin')
            assert page.locator('[data-config-section]:visible').count() == 1
            assert page.locator('input[name=value]').is_disabled()
            page.goto(base + '/installer-cache')
            page.locator('#source-choice').select_option('ubuntu_base')
            page.locator('#source-acquire').click()
            page.wait_for_function("document.getElementById('source-status').textContent.includes('Test fixture source acquisition completed')")
            assert page.locator('a[href="/installer-cache/source?source=ubuntu_base"]').is_visible()
            page.goto(base + '/hardware')
            assert page.locator('#baseline-shell-style').count() == 1
            page.get_by_role('button',name='Restart host',exact=True).click()
            page.wait_for_function("document.querySelector('.baseline-nav form [role=status]').textContent.includes('Your login expired')")
            assert page.locator('.baseline-nav form a[href="/login"]').is_visible()
            page.get_by_role('tab',name='Drives',exact=True).click()
            assert page.locator('#hardware-panel-drives').is_visible()
            assert page.locator('#hardware-panel-configuration').is_hidden()
            page.locator('a[href="/drive-admin?serial=hardware-drive"]').click()
            assert page.locator('input[name=targetDrive]:checked').input_value() == '/dev/sdc'
            page.goto(base + '/hardware#hardware-network')
            assert page.locator('#hardware-panel-network').is_visible()
            assert page.locator('#hardware-panel-network').get_by_text('Installed 6.0',exact=True).is_visible()
            assert page.locator('#hardware-panel-network a[href="/installer-cache#cache-entry-ethtool"]').is_visible()
            page.get_by_role('tab',name='Network',exact=True).focus()
            page.keyboard.press('ArrowRight')
            assert page.locator('#hardware-panel-graphics').is_visible()
            assert not errors, errors
            browser.close()
            print('Real Chromium: nested edits, autosave, compact fields, help, override, elevation, planner/recipe draft saves, restoration and concurrent-editor conflicts, Hardware tabs/package associations and serial drive navigation passed.')
    finally:
        server.shutdown()
        server.server_close()
        temporary.cleanup()


if __name__ == '__main__':
    main()
