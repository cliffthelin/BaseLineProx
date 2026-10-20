import baseline_web as bw
import chat_page
import hardware_overview as ho


def test_hardware_overview_rows_open_to_every_field():
    rows = [{"group": "CPU", "label": "Ryzen", "detail": "8 cores", "fields": {"speed": "4 GHz", "cache": "<b>"}}]
    html = ho.render_section(rows)
    assert "<details><summary>Ryzen</summary>" in html and "speed: 4 GHz" in html and "&lt;b&gt;" in html and "<b>" not in html


def test_hardware_overview_reports_an_error_instead_of_a_blank():
    assert "unavailable: inxi missing" in ho.render_section([], "inxi missing")
    rows, err = ho.overview_rows(lambda: (None, "boom"), lambda raw: [])
    assert rows == [] and err == "boom"
    rows, err = ho.overview_rows(lambda: ({"x": 1}, None), lambda raw: [{"group": "g", "label": "l", "detail": "d"}])
    assert err == "" and rows[0]["group"] == "g"


def test_chat_page_has_copy_last_answer():
    page = chat_page.render([("hi", "hello")], [("claude", "Claude")]).decode()
    assert "id='copy-last'" in page and "class='answer'" in page


def test_every_page_carries_the_status_strip_and_refresh():
    nav = bw.render_nav("/hardware")
    assert 'id="baseline-status"' in nav and 'id="baseline-refresh"' in nav


def test_status_line_reports_lifeline_and_assistant_and_is_cached(monkeypatch):
    import network
    monkeypatch.setattr(network, "check_lifeline", lambda: [{"fact": "internet_reachable", "ok": True, "detail": "ok"}])
    bw._STATUS_CACHE.update(at=0.0, value=None)
    first = bw._status_line({}, now=1000.0)
    assert first["network"] == "You are online" and first["network_detail"] == "online - lifeline up" and "assistant" in first
    monkeypatch.setattr(network, "check_lifeline", lambda: [{"fact": "dns_functioning", "ok": False, "detail": "x"}])
    assert bw._status_line({}, now=1010.0) == first                       # cached for 30 seconds
    later = bw._status_line({}, now=1100.0)
    assert later["network"] == "You are offline" and later["network_detail"] == "offline - stopped at dns_functioning"
