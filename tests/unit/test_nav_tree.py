import baseline_web as bw
import nav_tree


def test_every_page_is_reachable_exactly_once():
    paths = [p for p, _ in nav_tree.flatten()]
    assert len(paths) == len(set(paths))
    for required in ("/launcher", "/hardware", "/settings", "/install-plan", "/installer-cache", "/managed-mode", "/recovery", "/drive-admin"):
        assert required in paths


def test_server_managed_is_its_own_group_inside_the_installer():
    installer = dict(nav_tree.TREE)["Installer"]
    names = [e[0] for e in installer if not nav_tree.is_page(e)]
    assert "Server managed" in names


def test_nav_tabs_are_derived_from_the_tree_and_the_open_group_follows_the_page():
    assert bw.NAV_TABS == nav_tree.flatten()
    assert nav_tree.active_group("/managed-mode") == "Installer" and nav_tree.active_group("/hardware") == "Machine"
    html = bw.render_nav("/managed-mode")
    assert '<details class="nav-group" open><summary>Installer' in html and "Server managed" in html
