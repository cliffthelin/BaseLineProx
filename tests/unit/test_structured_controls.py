import html
import structured_controls as sc


def test_nested_setting_has_typed_editor_and_opt_in_override():
    result = sc.render('tool', {'install': 'automatic', 'fields': []})
    assert 'data-structured-editor' in result
    assert 'type="hidden" name="tool"' in result
    assert '<details' in result and 'Advanced JSON override' in result
    assert 'disabled' in result
    assert html.escape('{"install": "automatic", "fields": []}', quote=True) in result


def test_script_has_supported_selectors_and_no_html_injection():
    result = sc.script()
    assert "createElement('select')" in result
    assert 'textContent' in result
    assert '.innerHTML' not in result


def test_all_json_pages_use_options_first_controls():
    import install_plan_page, recipe_page, settings_web
    for page in (install_plan_page.render(), recipe_page.render(),
                 settings_web.render_settings_page({'custom': {'nested': {'enabled': True}}})):
        source = page.decode()
        assert 'BaselineStructuredEditor' in source
        assert 'Advanced JSON override' in source
    assert 'Build choices (JSON)' not in install_plan_page.render().decode()
