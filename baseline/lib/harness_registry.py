"""Dispatch layer that makes harness adapters actually swappable (item
5, docs/design/v0.1-work-queue.md). Before this existed,
`bin/baseline` hardcoded `import harness` and called
`harness.ask_streaming(...)` directly no matter which harness the
operator selected in the Chat tab's dropdown - the selection had no
effect on which module ever actually ran, since only one ever could.
This module is the fix: `get_adapter(harness_id)` is the one place
that decides which module backs a given id, importing it lazily
rather than every adapter module being imported unconditionally at
startup whether selected or not.
"""
from __future__ import annotations

import importlib

import providers
import harness_adapter


def adapter_module_name(harness_id: str):
    """The importable module name for `harness_id`, or None if it's
    unknown or not implemented. Pure lookup against
    providers.HARNESSES - no import happens here."""
    for entry in providers.HARNESSES:
        if entry["id"] == harness_id:
            return entry.get("adapter_module")
    return None


def get_adapter(harness_id: str):
    """The real adapter module for `harness_id`, or None if it's
    unknown, not implemented, or (defensively) named but doesn't
    actually conform to the HarnessAdapter contract - never raises."""
    module_name = adapter_module_name(harness_id)
    if not module_name:
        return None
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return None
    return module if harness_adapter.conforms(module) else None


def supports_write_grant(adapter) -> bool:
    """Whether `adapter` exposes the optional, Claude-Code-specific
    write-grant capability (grant_write_scope/revoke_write_scope) -
    never assumed, since different harnesses' CLIs have different (or
    no) permission-scoping mechanisms of their own."""
    if adapter is None:
        return False
    return callable(getattr(adapter, "grant_write_scope", None)) and \
        callable(getattr(adapter, "revoke_write_scope", None))
