"""Unit tests for clipboard_osc52.py - the standard OSC 52 escape
sequence a TUI uses to reach the *local* clipboard of whatever
terminal is attached, over SSH included. Pure function only; whether
it actually works over this specific console/SSH path is a real-
hardware verification question this test suite cannot answer (see
docs/design/v0.1-work-queue.md item 7)."""
import base64

import clipboard_osc52 as osc


def test_wraps_the_base64_payload_in_the_osc52_escape_sequence():
    seq = osc.build_osc52_copy_sequence("hello")
    expected_payload = base64.b64encode(b"hello").decode("ascii")
    assert seq == f"\x1b]52;c;{expected_payload}\x07"


def test_encodes_unicode_as_utf8_before_base64():
    seq = osc.build_osc52_copy_sequence("héllo")
    expected_payload = base64.b64encode("héllo".encode("utf-8")).decode("ascii")
    assert seq == f"\x1b]52;c;{expected_payload}\x07"


def test_selection_buffer_defaults_to_clipboard():
    seq = osc.build_osc52_copy_sequence("x")
    assert seq.startswith("\x1b]52;c;")


def test_selection_buffer_is_configurable():
    seq = osc.build_osc52_copy_sequence("x", selection="p")
    assert seq.startswith("\x1b]52;p;")


def test_empty_string_still_produces_a_well_formed_sequence():
    seq = osc.build_osc52_copy_sequence("")
    assert seq == "\x1b]52;c;\x07"
