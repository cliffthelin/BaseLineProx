"""Owner-scoped display configuration through the authenticated Installer API."""
import json
from test_baseline_web import _RealServerCase, _base_deps
import configuration_drafts


def test_display_mode_is_saved_separately_from_the_installation_plan(tmp_path):
    store = configuration_drafts.DraftStore(tmp_path / 'drafts.sqlite')
    case = _RealServerCase(_base_deps(draft_store=store))
    document = {'version': 1, 'display_mode': 'desktop', 'manager_mode': 'split',
                'active_page': 'baseline', 'pages': [{'id': 'baseline', 'name': 'Baseline',
                'kind': 'baseline', 'desktop': [], 'groups': [], 'configuration': {}}]}
    try:
        status, saved = case.post_json('/install-plan/display', {'document': document, 'revision': 0})
        assert status == 200
        assert saved['draft']['document'] == document
        status, raw = case.get('/install-plan/display')
        assert status == 200 and json.loads(raw)['draft']['document'] == document
        assert store.get('root', 'installer') is None
        assert store.get('another-user', 'installer-display') is None
        status, result = case.post_json('/install-plan/display', {'document': document, 'revision': 0})
        assert status == 409 and 'another editor' in result['message']
    finally:
        case.close()


def test_display_rejects_duplicate_pages_and_dangling_group_selection(tmp_path):
    import pytest
    store = configuration_drafts.DraftStore(tmp_path / 'drafts.sqlite')
    page = {'id': 'one', 'name': 'VM one', 'kind': 'vm', 'desktop': [], 'groups': [], 'configuration': {}}
    document = {'version': 1, 'display_mode': 'desktop', 'manager_mode': 'split', 'active_page': 'one', 'pages': [page, page]}
    with pytest.raises(configuration_drafts.DraftError, match='unique'):
        store.save('root', 'installer-display', document, expected_revision=0)
    document['pages'] = [page]
    document['active_page'] = 'missing'
    with pytest.raises(configuration_drafts.DraftError, match='active page'):
        store.save('root', 'installer-display', document, expected_revision=0)


def test_provisioning_installs_display_module_required_by_the_web_application():
    from pathlib import Path
    provision = (Path(__file__).resolve().parents[2] / 'boot/provision.sh').read_text()
    assert 'cp "$SRC/baseline/lib/installer_desktop.py" /opt/baseline/lib/installer_desktop.py' in provision


def test_installer_has_a_direct_desktop_menu_entry():
    case = _RealServerCase(_base_deps())
    try:
        status, raw = case.get('/install-plan')
        assert status == 200
        assert b'href="/install-plan?display=desktop"' in raw
        assert b'Installer desktop' in raw
    finally:
        case.close()
