#!/usr/bin/env python3
"""Actual browser/HTTP flow against synthetic devices; never physical proof."""
from pathlib import Path
import sys
import tempfile
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'unit'),str(Path(__file__).resolve().parents[2]/'baseline/lib')]
from playwright.sync_api import sync_playwright, expect
from test_baseline_web import _RealServerCase,_base_deps,FakeSudoExecutor
from test_drive_admin import FakePdsRunner
from test_installer_inputs import repository
import workload_jobs
import configuration_drafts
from test_install_plan import discover,proxmox_disk,baseline_disk

with tempfile.TemporaryDirectory(prefix='baseline-auto-browser-') as temporary:
    root=Path(temporary)
    jobs=workload_jobs.WorkloadJobs(root/'jobs.sqlite')
    executor=FakeSudoExecutor(stdout=b'{"state":"updated","boot_verified":false}\n')
    case=_RealServerCase(_base_deps(workload_jobs=jobs,installer_bundle_root=root/'bundles',
        installer_repo_root=repository(root/'source'),
        draft_store=configuration_drafts.DraftStore(root/'drafts.sqlite'),
        install_plan_discovery=lambda:discover(proxmox_disk(),baseline_disk()),
        installer_selected_serial='SYNTHDRIVEB00002',installer_protected_serials=['SYNTHDRIVEA00001'],
        installed_update_discovery=lambda serial:'/dev/sdb',
        installed_update_recovery=lambda serial:root/'recovery',pds_runner=FakePdsRunner(),pkexec_executor=executor))
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            context=browser.new_context(viewport={'width':1800,'height':1200})
            context.add_cookies([{'name':'session','value':case.token,'url':f'http://127.0.0.1:{case.port}'}])
            page=context.new_page()
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{case.port}/install-plan')
            page.locator('[data-drive-serial="SYNTHDRIVEB00002"]').wait_for()
            page.locator('[data-drive-serial="SYNTHDRIVEB00002"]').drag_to(page.locator('#installation-target'))
            assert 'SYNTHDRIVEB00002' in page.locator('#installation-target').inner_text()
            assert page.locator('[data-drive-serial="SYNTHDRIVEA00001"]').get_attribute('draggable')=='false'
            page.locator('[data-os-variant="server"]').scroll_into_view_if_needed()
            page.screenshot(path='/tmp/baseline-installer-before-drag.png', full_page=True)
            page.locator('[data-os-variant="server"]').drag_to(page.locator('#environment-target'))
            expect(page.locator('#environment-target')).to_contain_text('Ubuntu 24.04 server')
            page.locator('#application-shortcuts [data-app-id="chrome"]').drag_to(page.locator('#application-target'))
            assert 'Ubuntu 24.04 server' in page.locator('#environment-target').inner_text()
            expect(page.locator('#application-target')).to_contain_text('Google Chrome')
            page.locator('#application-shortcuts [data-app-id="chrome"]').click(button='right')
            page.locator('#shortcut-details[open]').wait_for()
            page.locator('#shortcut-settings-form input[name="scale"]').fill('1.25')
            page.locator('#shortcut-settings-form button[type="submit"]').click()
            page.locator('#shortcut-details').wait_for(state='hidden')
            assert case.server.deps['draft_store'].get('root','installer')['document']['applications']['configurations']['chrome']['scale']==1.25
            page.set_viewport_size({'width':1800,'height':1000})
            assert page.locator('.installer-workspace').bounding_box()['width']>1700
            page.set_viewport_size({'width':500,'height':900})
            assert page.locator('.installer-workspace').bounding_box()['width']<500
            page.set_viewport_size({'width':1280,'height':1000})
            page.screenshot(path='/tmp/baseline-installer-grouped-desktop.png', full_page=True)
            page.locator('#start-installation-update').click()
            page.locator('#update-status').filter(has_text='Deployment complete').wait_for(timeout=30000)
            assert page.locator('#update-serial').input_value()=='SYNTHDRIVEB00002'
            assert page.locator('#update-input-job').input_value()
            assert 'SYNTHDRIVEB00002' in executor.calls[0][0]
            assert page.locator('#update-secret').input_value()==''
            assert not errors,errors
            assert len(jobs.listing())==2 and all(job['state']=='completed' for job in jobs.listing())
            assert len(executor.calls)==1 and executor.calls[0][0][0]=='pkexec'
            browser.close()
            print('PASS: real Chromium automatically captured inputs and executed exact-serial native update; synthetic devices/executor, no physical execution.')
    finally:
        case.close()
