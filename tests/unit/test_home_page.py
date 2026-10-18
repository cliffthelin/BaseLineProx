"""The browser's starting page (operator, 2026-10-14: the installer plan was not where things were meant to start): the same six areas as
the TUI first, then the machine's own tools, with the installer and administration kept out of the way."""
import home_page as hp


def test_the_home_page_leads_with_the_tui_areas_in_the_tui_order():
    html = hp.render().decode()
    order = [html.index(f'href="{p}"') for p in ("/hardware", "/network", "/sensors", "/vms", "/chat", "/shell")]
    assert order == sorted(order)
    assert html.index('href="/hardware"') < html.index('href="/install-plan"')


def test_proxmox_and_the_installer_are_reachable_but_not_the_front():
    html = hp.render().decode()
    assert 'https://localhost:8006' in html and 'href="/console"' in html
    assert hp.INSTALLER_GROUP and "/install-plan" in [p for p, _ in hp.INSTALLER_GROUP]


def test_the_navigation_starts_with_home_and_the_tui_tabs_and_ends_with_the_installer():
    import baseline_web as bw
    paths = [p for p, _ in bw.NAV_TABS]
    assert paths[0] == "/home"
    assert paths[1] == "/launcher"            # DR259 (operator 2026-10-14): the phone-style launcher is where VMs/OSes start
    # the navigation is nested categories now (nav_tree.py, operator 2026-10-18); the TUI's pages are still all present and the installer still comes last
    assert {"/hardware", "/network", "/sensors", "/vms", "/chat", "/shell"} <= set(paths)
    assert paths.index("/install-plan") > paths.index("/vault") > paths.index("/shell")
    assert len(paths) == len(set(paths))
