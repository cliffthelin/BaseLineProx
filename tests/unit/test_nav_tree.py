import baseline_web as bw
import nav_tree as nt


def test_every_page_is_reachable_exactly_once():
    paths = [p for p, _ in nt.flatten()]
    assert len(paths) == len(set(paths))
    for required in ("/launcher", "/hardware", "/settings", "/install-plan", "/installer-cache", "/managed-mode", "/recovery", "/drive-admin", "/web-address"):
        assert required in paths


def test_server_managed_is_its_own_group_inside_the_installer():
    installer = next(g for g in nt.TREE if g.advanced == "Installer")
    assert "Server managed" in [e.advanced for e in installer.items if isinstance(e, nt.Group)]


def test_simple_mode_shows_fewer_pages_with_plain_names_and_advanced_shows_all():
    simple, advanced = nt.visible_in(nt.SIMPLE), nt.visible_in(nt.ADVANCED)
    assert set(simple) < set(advanced) and set(advanced) == {p for p, _ in nt.flatten()}
    for technical in ("/shell", "/ceph", "/audit", "/master-config", "/workloads", "/containers"):
        assert technical not in simple
    assert "/hardware" in simple and "/recovery" in simple and "/managed-mode" in simple


def test_every_simple_page_has_a_plain_name_that_differs_from_a_jargon_label_somewhere():
    for group in nt.TREE:
        for e in group.items:
            pages = [e] if isinstance(e, nt.Page) else list(e.items)
            for p in pages:
                if p.simple is not None:
                    assert p.simple.strip() and "  " not in p.simple


def test_nav_tabs_follow_the_tree_the_open_group_follows_the_page_and_both_modes_render():
    assert bw.NAV_TABS == nt.flatten()
    assert nt.active_group("/managed-mode") == "Installer" and nt.active_group("/hardware") == "Machine"
    html = bw.render_nav("/managed-mode")
    assert '<details class="nav-group" open><summary>' in html and "Parent server" in html and "Server managed" in html
    assert 'class="m-simple">About this computer' in html and 'class="m-adv">Hardware' in html and 'data-mode="advanced"' in html
    assert 'href="/shell" class=" adv"' in html           # the command line is hidden from the simple view
