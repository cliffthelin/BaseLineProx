"""The browser page that shows the Baseline text console: only the machine itself may switch its own screen."""
import pytest

import console_switch as cs


def test_only_loopback_addresses_are_the_machine_itself():
    assert cs.is_local("127.0.0.1") and cs.is_local("::1") and cs.is_local("::ffff:127.0.0.1")
    for other in ("10.0.0.192", "192.168.1.5", "fe80::1%vmbr0", "2601:681::1", "not-an-address", ""):
        assert not cs.is_local(other)


def test_the_switch_runs_chvt_for_the_console_or_the_browser_and_nothing_else():
    calls = []

    class Done:
        returncode = 0

    def run(argv, **kwargs):
        calls.append(argv)
        return Done()

    assert cs.switch(run=run) is True and cs.switch(cs.BROWSER_VT, run=run) is True
    assert calls == [["chvt", "1"], ["chvt", "3"]]
    with pytest.raises(ValueError):
        cs.switch(2, run=run)


def test_the_page_has_one_button_that_posts_and_names_the_way_back():
    html = cs.page().decode()
    assert 'method="post" action="/console/switch"' in html and html.count("<button") == 1
    assert "Ctrl" in html and "F1" in html and "F3" in html
