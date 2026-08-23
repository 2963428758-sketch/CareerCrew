"""工具结果体积钳制测试：检索类工具的大块返回不得无上限驻留上下文。"""
from __future__ import annotations

from langchain_core.messages import ToolMessage

from careercrew_ai.agents.langchain_agent import MaxIterationsMiddleware


class _Req:
    def __init__(self, tool_call_id: str = "call-1"):
        self.tool_call = {"id": tool_call_id, "name": "rag_query", "args": {}}
        self.state = {}


def test_small_tool_result_untouched() -> None:
    mw = MaxIterationsMiddleware(10)
    small = ToolMessage(content="正常长度的检索结果", tool_call_id="call-1", name="rag_query")
    out = mw.wrap_tool_call(_Req(), lambda _r: small)
    assert out is small  # 原对象透传，不做拷贝


def test_oversized_tool_result_clamped() -> None:
    mw = MaxIterationsMiddleware(10)
    big_text = "x" * 50_000
    big = ToolMessage(content=big_text, tool_call_id="call-1", name="rag_query")
    out = mw.wrap_tool_call(_Req(), lambda _r: big)
    assert isinstance(out, ToolMessage)
    assert len(out.content) < len(big_text)
    assert "已截断" in out.content
    assert out.content.startswith("x")  # 头部正文保留
    assert out.content.rstrip().endswith(big_text[-60:-40]) or big_text[-200:] in out.content  # 尾部保留


def test_non_tool_message_passthrough() -> None:
    mw = MaxIterationsMiddleware(10)
    weird = object()  # 非 ToolMessage 返回（防御性）
    out = mw.wrap_tool_call(_Req(), lambda _r: weird)
    assert out is weird


def test_tool_exception_still_fed_back() -> None:
    mw = MaxIterationsMiddleware(10)

    def boom(_r):
        raise RuntimeError("检索服务不可用")

    out = mw.wrap_tool_call(_Req(), boom)
    assert isinstance(out, ToolMessage)
    assert "Error" in out.content and "检索服务不可用" in out.content
