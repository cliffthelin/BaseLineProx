import console_theme as ct
import baseline_web as bw


def test_every_wrapped_page_gets_the_one_shared_stylesheet():
    page = bw._with_nav(b"<html><head></head><body><h1>x</h1></body></html>", "/hardware").decode()
    assert page.count('id="baseline-shell-style"') == 1 and "--accent" in page and ".tiles" in page


def test_components_pages_are_built_from_exist_in_the_theme():
    for selector in (".page-head", ".eyebrow", ".grid", ".card", ".tiles", ".seg", ".switch", ".chips", ".btn", ".note"):
        assert selector in ct.CSS


def test_both_themes_resolve_and_the_destructive_nav_button_is_not_styled_as_primary():
    assert "color-scheme:dark" in ct.CSS and ".baseline-nav form button[type=submit]" in ct.CSS


def test_the_pages_i_rebuilt_use_choices_before_typing():
    import managed_mode_page, web_address_page
    m = managed_mode_page.render({"mode": "standalone"}, [{"folder": "/mnt/x", "volume": "/mnt/x"}]).decode()
    w = web_address_page.render({"bind_host": "0.0.0.0", "port": 8100}, ["10.0.0.5"]).decode()
    assert 'class="tiles"' in m and 'class="switch"' in m and 'class="path-picker"' in m and "Browse" in m and 'id="other"' not in m
    assert m.count('type="text"') == 1 and 'class="pp-paste"' in m                    # the only text box is the paste-only, validated one
    assert m.count('<p class="lead">') == 1                                         # one description
    assert 'class="tiles"' in w and 'class="chips"' in w and 'type="number"' not in w


def test_settings_render_as_cards_with_the_right_control_for_each_kind_of_value():
    import settings_ui
    import settings_web as sw
    page = settings_ui.render_sections({"drivers": {"cpu_microcode": True, "cpu_microcode_package": "amd64-microcode"}, "network": {"hostname": "baseline"},
                                        "handoff": {"restored_categories": [], "archive_path": ""}},
                                       render_field_input=sw.render_field_input, field_choices=sw._FIELD_CHOICES)
    assert page.count('class="card settings-card') == 3 and 'class="switch"' in page and 'class="seg"' in page and 'type="text"' in page
    assert "Keep processor fixes up to date" in page and '<code class="adv">cpu_microcode</code>' in page       # plain name first, the real key kept for Advanced
    assert 'name="cpu_microcode__type" value="bool"' in page and 'action="/settings/drivers"' in page and "data-autosave" in page
    assert 'settings-card adv' in page                                                                      # list-valued data is advanced-only


def test_a_setting_without_words_is_still_shown_with_a_name_made_from_its_key():
    import settings_ui
    import settings_web as sw
    page = settings_ui.render_sections({"network": {"brand_new_option": True}}, render_field_input=sw.render_field_input, field_choices=sw._FIELD_CHOICES)
    assert "Brand new option" in page and "brand_new_option" in page
