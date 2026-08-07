"""B5 工具注册表测试。"""
from __future__ import annotations

import pytest
from langchain_core.tools import BaseTool, tool

from careercrew_core.tools.internal.memory_search import memory_search
from careercrew_core.tools.registry import ToolRegistry, ToolSpec


@tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@tool
def submit_application(company: str) -> str:
    """Submit job application (high risk)."""
    return f"applied to {company}"


def test_register_and_get() -> None:
    reg = ToolRegistry()
    reg.register(ToolSpec(tool=add))
    assert reg.has("add")
    assert reg.get("add").name == "add"
    assert reg.list_names() == ["add"]


def test_get_unknown_raises() -> None:
    reg = ToolRegistry()
    with pytest.raises(KeyError):
        reg.get("nope")


def test_high_risk_identified() -> None:
    reg = ToolRegistry()
    reg.register(ToolSpec(tool=add))
    reg.register(ToolSpec(tool=submit_application, requires_confirmation=True))
    assert reg.high_risk_names() == ["submit_application"]


def test_source_and_parallel_safe_defaults() -> None:
    spec = ToolSpec(tool=add)
    assert spec.source == "internal"
    assert spec.parallel_safe is True
    assert spec.requires_confirmation is False


def test_execute_internal_tool() -> None:
    reg = ToolRegistry()
    reg.register(ToolSpec(tool=add))
    assert reg.execute("add", a=3, b=5) == 8


def test_bindable_tools_are_basetool() -> None:
    reg = ToolRegistry()
    reg.register(ToolSpec(tool=memory_search))
    bindable = reg.bindable_tools()
    assert len(bindable) == 1
    assert isinstance(bindable[0], BaseTool)


def test_memory_search_stub_runs() -> None:
    reg = ToolRegistry()
    reg.register(ToolSpec(tool=memory_search))
    out = reg.execute("memory_search", query="RAG 面试题", top_k=3)
    assert "stub" in out
    assert "RAG 面试题" in out
