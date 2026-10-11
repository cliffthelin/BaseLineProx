"""tools/vm-console: the keystrokes it sends for text, checked against the QEMU key names."""
import importlib.machinery
import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "tools" / "vm-console"
_loader = importlib.machinery.SourceFileLoader("vm_console", str(_PATH))
vc = importlib.util.module_from_spec(importlib.util.spec_from_loader("vm_console", _loader))
_loader.exec_module(vc)


def test_letters_digits_and_enter_become_qemu_key_names():
    assert vc.keys("ab1\n") == ["sendkey a", "sendkey b", "sendkey 1", "sendkey ret"]


def test_capitals_and_punctuation_use_shift_chords():
    assert vc.keys("A_") == ["sendkey shift-a", "sendkey shift-minus"]
    assert vc.keys("/-.:") == ["sendkey slash", "sendkey minus", "sendkey dot", "sendkey shift-semicolon"]


def test_every_punctuation_a_shell_command_needs_has_a_key():
    for ch in "|&;$()<>*'\"{}[]#%@?=+~!\\,^`":
        assert not vc.keys(ch)[0].endswith(ch) or ch.isalnum(), ch
