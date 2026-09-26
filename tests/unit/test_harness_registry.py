"""Unit tests for harness_registry.py - the dispatch layer that makes
harness adapters actually swappable (item 5, docs/design/v0.1-work-queue.md).
Before this, bin/baseline hardcoded `import harness` and called
`harness.ask_streaming(...)` directly regardless of which harness the
operator selected - the dropdown had no effect on which module ever
actually ran. This registry is what fixes that."""
import providers
import harness_registry as reg


def test_adapter_module_name_for_claude():
    assert reg.adapter_module_name("claude") == "harness"


def test_adapter_module_name_for_opencode():
    assert reg.adapter_module_name("opencode") == "opencode_adapter"


def test_adapter_module_name_none_for_a_genuinely_unimplemented_harness():
    assert reg.adapter_module_name("hermes") is None


def test_adapter_module_name_none_for_an_unknown_id():
    assert reg.adapter_module_name("does-not-exist") is None


def test_every_harnesses_entry_agrees_with_implemented_flag():
    # A structural check on providers.HARNESSES itself, not a fake -
    # "implemented: True" and "adapter_module: <something importable>"
    # must never disagree, or the registry and the dropdown would lie
    # to each other.
    for entry in providers.HARNESSES:
        if entry["implemented"]:
            assert entry.get("adapter_module"), f"{entry['id']} is implemented but names no adapter_module"
        else:
            assert not entry.get("adapter_module"), f"{entry['id']} names an adapter_module but implemented=False"


def test_get_adapter_returns_the_real_harness_module_for_claude():
    adapter = reg.get_adapter("claude")
    assert adapter is not None
    assert adapter.__name__ == "harness"
    assert hasattr(adapter, "ask")
    assert hasattr(adapter, "ask_streaming")
    assert hasattr(adapter, "new_session")
    assert hasattr(adapter, "describe_session")


def test_get_adapter_returns_the_real_opencode_adapter_through_the_same_generic_dispatch():
    # The whole point of the registry: adding a real second harness
    # was a matter of one adapter module + one HARNESSES entry, not a
    # bin/baseline rewrite. This proves get_adapter is genuinely
    # generic, not secretly special-cased for "claude".
    adapter = reg.get_adapter("opencode")
    assert adapter is not None
    assert adapter.__name__ == "opencode_adapter"
    assert hasattr(adapter, "ask")
    assert hasattr(adapter, "ask_streaming")
    assert hasattr(adapter, "new_session")
    assert hasattr(adapter, "describe_session")


def test_get_adapter_returns_none_for_a_genuinely_unimplemented_harness():
    assert reg.get_adapter("hermes") is None


def test_supports_write_grant_false_for_opencode():
    # Optional per the contract - OpenCode's adapter deliberately
    # doesn't implement this (decision record 44), and the registry
    # must never assume every adapter has it.
    assert reg.supports_write_grant(reg.get_adapter("opencode")) is False


def test_get_adapter_returns_none_for_an_unknown_id():
    assert reg.get_adapter("does-not-exist") is None


def test_supports_write_grant_true_for_claude():
    assert reg.supports_write_grant(reg.get_adapter("claude")) is True


def test_supports_write_grant_false_for_a_module_missing_the_hooks():
    class FakeAdapter:
        def ask(self, prompt, *, session=None, runner=None):
            return "stub"
    assert reg.supports_write_grant(FakeAdapter()) is False


def test_supports_write_grant_false_for_none():
    assert reg.supports_write_grant(None) is False
