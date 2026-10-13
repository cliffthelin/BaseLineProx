"""Browser parity for the TUI's Tether action and Chat tab: shared wording for the tether outcome, and a chat page that never echoes a
credential and says plainly when no harness is set up."""
import chat_page as cp


def test_the_tether_outcome_reads_the_same_in_the_tui_and_the_browser():
    ok = cp.tether_message({"ok": True, "interface": "usb0", "address": "10.0.0.7"})
    bad = cp.tether_message({"ok": False, "stage": "no_carrier", "detail": "usb0 has no carrier"})
    assert ok == ("information", "USB tether connected on usb0: 10.0.0.7")
    assert bad == ("error", "USB tether no_carrier: usb0 has no carrier")
    assert cp.tether_message({"ok": False})[1] == "USB tether unknown: no diagnostic detail provided"


def test_the_chat_page_lists_the_exchange_escaped_and_offers_the_harness_choices():
    html = cp.render([("<b>hi</b>", "answer & more")], [("claude", "Claude Code")], notice="").decode()
    assert "&lt;b&gt;hi&lt;/b&gt;" in html and "answer &amp; more" in html
    assert 'action="/chat/ask"' in html and "Claude Code" in html


def test_a_question_must_be_one_to_four_thousand_characters():
    assert cp.clean_question("  what is the temperature? ") == "what is the temperature?"
    for bad in ("", "   ", "x" * 4001):
        try:
            cp.clean_question(bad)
        except ValueError:
            continue
        raise AssertionError(bad[:10])
