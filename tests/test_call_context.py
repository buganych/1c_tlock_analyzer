"""Unit tests for CALL context resolution."""

from datetime import datetime

from tj_common.call_context import resolve_call_context, resolve_call_event_context
from tj_common.models_call import CallEvent


def test_resolve_context_priority():
    assert resolve_call_context(context="Ctx") == "Ctx"
    assert resolve_call_context(module="M", method="meth") == "M.meth"
    assert resolve_call_context(func="MyFunc") == "MyFunc"
    assert resolve_call_context(mname="Mod", iname="Item") == "Mod.Item"
    assert resolve_call_context(mname="Mod") == "Mod"
    assert resolve_call_context(iname="Item") == "Item"
    assert resolve_call_context() == "(unknown)"


def test_resolve_call_event_context():
    event = CallEvent(
        ts=datetime(2026, 6, 4),
        module="CommonModule",
        method="DoWork",
        func="IgnoredWhenModuleMethod",
    )
    assert resolve_call_event_context(event) == "CommonModule.DoWork"
