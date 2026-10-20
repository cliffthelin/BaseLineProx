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


class HarnessAdapterError(RuntimeError):
    """A configured harness is advertised but its real adapter is broken."""


def adapter_module_name(harness_id: str):
    """The importable module name for `harness_id`, or None if it's
    unknown or not implemented. Pure lookup against
    providers.HARNESSES - no import happens here."""
    for entry in providers.HARNESSES:
        if entry["id"] == harness_id:
            return entry.get("adapter_module")
    return None


def get_adapter(harness_id: str):
    """Load a real adapter; return None only for an unknown/unimplemented ID.

    A declared adapter that cannot be imported or violates the contract is a
    configuration/runtime error, never an apparent absence of a selection.
    """
    entry=next((item for item in providers.HARNESSES if item.get('id')==harness_id),None)
    if entry is None or not entry.get('implemented'):
        return None
    module_name=entry.get('adapter_module')
    if not isinstance(module_name,str) or not module_name:
        raise HarnessAdapterError(f"harness {harness_id!r} is marked implemented but has no adapter module")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise HarnessAdapterError(f"harness {harness_id!r} adapter {module_name!r} cannot be imported: {exc}") from exc
    if not harness_adapter.conforms(module):
        raise HarnessAdapterError(f"harness {harness_id!r} adapter {module_name!r} does not satisfy the adapter contract")
    return module


def supports_write_grant(adapter) -> bool:
    """Whether `adapter` exposes the optional, Claude-Code-specific
    write-grant capability (grant_write_scope/revoke_write_scope) -
    never assumed, since different harnesses' CLIs have different (or
    no) permission-scoping mechanisms of their own."""
    if adapter is None:
        return False
    return callable(getattr(adapter, "grant_write_scope", None)) and \
        callable(getattr(adapter, "revoke_write_scope", None))
