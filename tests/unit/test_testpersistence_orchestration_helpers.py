"""Tests for the orchestration-script helpers that guard against a
secret leaking through an unhandled-exception path (found by
independent review of the TestPersistence Phase B / Milestone 5
harnesses - see docs/design/decision-records/28 and 29). A bare
`raise` of an exception carrying raw console-buffer text (e.g.
ConsoleTimeout, StepFailed) would print that text, unsanitized, via
the default excepthook. sanitized_failure_message() is the fix: every
exception's message is rendered through the same sanitization
Evidence.record() uses before it can ever reach stderr."""
import testpersistence_phaseB_vertical_slice as m


class _FakeEvidence:
    def __init__(self, deny_substrings):
        self.deny_substrings = deny_substrings


def test_sanitized_failure_message_redacts_a_known_secret():
    secret = "synthetic-luks-passphrase-abc123"
    exc = m.StepFailed(f"guest did not respond, last buffer: ...{secret}...")
    ev = _FakeEvidence(deny_substrings=(secret,))
    message = m.sanitized_failure_message(exc, ev)
    assert secret not in message
    assert "<redacted>" in message


def test_sanitized_failure_message_redacts_absolute_host_paths_even_with_no_ev():
    exc = m.StepFailed("console dump: /home/someone/experiments/run1")
    message = m.sanitized_failure_message(exc, ev=None)
    assert "/home/someone" not in message
    assert "<redacted-host-path>" in message


def test_sanitized_failure_message_redacts_console_timeout_buffer_tail():
    """The concrete failure scenario the reviewer identified: a
    ConsoleTimeout carries the raw serial buffer tail, which may
    still contain secret-bearing text if it arrived before `stty
    -echo` took effect."""
    import qemu_serial_console as console

    secret = "synthetic-manifest-key-deadbeef"
    exc = console.ConsoleTimeout(
        f"did not see 'MARKER' within 10s - last buffer tail: '...{secret}...'")
    ev = _FakeEvidence(deny_substrings=(secret,))
    message = m.sanitized_failure_message(exc, ev)
    assert secret not in message


def test_sanitized_failure_message_leaves_non_secret_text_alone():
    exc = m.StepFailed("TestSystem-A did not shut down cleanly")
    message = m.sanitized_failure_message(exc, ev=None)
    assert "TestSystem-A" in message
    assert "did not shut down cleanly" in message
