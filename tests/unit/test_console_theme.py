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
    m = managed_mode_page.render({"mode": "standalone"}, [{"folder": "/mnt/x/baseline-vault", "volume": "/mnt/x"}]).decode()
    w = web_address_page.render({"bind_host": "0.0.0.0", "port": 8100}, ["10.0.0.5"]).decode()
    assert 'class="tiles"' in m and 'class="switch"' in m and "Another place" in m and '<details class="reveal"' in m
    assert 'class="tiles"' in w and 'class="chips"' in w and 'type="number"' not in w
