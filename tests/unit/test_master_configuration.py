import master_configuration as mc


def test_master_uses_current_section_routes_and_filters():
    page = mc.render({'diagnostics': {'ethtool_autoneg': 'on'}},
                     {'sessions': {'default_session_ttl_hours': 24}}, elevated=False,
                     additional=[('Operations', '/operations', {'backup': {'interval_hours': 48}})]).decode()
    assert 'id="config-search"' in page
    assert 'id="config-filter"' in page
    assert '/settings/diagnostics' in page
    assert '/admin/settings/sessions/default_session_ttl_hours' in page
    assert 'disabled' in page
    assert 'interval_hours' in page and '48' in page
    assert 'data-config-section' in page
    assert 'textarea name=' not in page


def test_master_escapes_external_configuration_and_reports_unavailability():
    page = mc.render({}, {}, additional=[('VMs', '/vms', {'name': '<script>bad</script>'})],
                     errors=['VM source unavailable']).decode()
    assert '<script>bad</script>' not in page
    assert '&lt;script&gt;bad&lt;/script&gt;' in page
    assert 'VM source unavailable' in page
