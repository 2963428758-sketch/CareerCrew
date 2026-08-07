"""B2 手写 ReAct 循环测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from careercrew_ai.react.react_loop import AgentResult, ReactLoop


@tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


class FakeChatModel:
    """按预设序列返回 AIMessage 的假 LLM（支持 bind_tools 占位）。"""

    def __init__(self, responses: list[AIMessage]) -> None:
        self.responses = list(responses)
        self._i = 0
        self.invoke_calls = 0

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages, config=None):
        self.invoke_calls += 1
        resp = self.responses[self._i]
        self._i += 1
        return resp


def _tc(name: str, args: dict, id_: str = "1") -> dict:
    return {"name": name, "args": args, "id": id_, "type": "tool_call"}


def test_tool_call_then_final() -> None:
    llm = FakeChatModel([
        AIMessage(content="", tool_calls=[_tc("add", {"a": 1, "b": 2}, "c1")]),
        AIMessage(content="结果是 3"),
    ])
    loop = ReactLoop(max_iterations=5)
    result = loop.run("你是计算器", [HumanMessage(content="算 1+2")], [add], llm)
    assert isinstance(result, AgentResult)
    assert result.content == "结果是 3"
    assert result.stopped_reason == "final_answer"
    assert result.tool_calls_total == 1
    assert len(result.iterations) == 2
    # 第一轮：有 tool_call 且执行结果回喂
    assert result.iterations[0].tool_calls[0]["name"] == "add"
    assert result.iterations[0].tool_results == [3]
    # 第二轮：无 tool_call（最终答案）
    assert result.iterations[1].tool_calls == []


def test_no_tool_call_immediate() -> None:
    llm = FakeChatModel([AIMessage(content="直接回答")])
    loop = ReactLoop()
    result = loop.run("sys", [HumanMessage(content="hi")], [add], llm)
    assert result.stopped_reason == "final_answer"
    assert result.content == "直接回答"
    assert len(result.iterations) == 1
    assert result.tool_calls_total == 0


def test_max_iterations() -> None:
    # LLM 一直返回 tool_call -> 超过 max_iterations
    llm = FakeChatModel([
        AIMessage(content="", tool_calls=[_tc("add", {"a": 1, "b": 1}, f"c{i}")]) for i in range(10)
    ])
    loop = ReactLoop(max_iterations=3)
    result = loop.run("sys", [HumanMessage(content="x")], [add], llm)
    assert result.stopped_reason == "max_iterations"
    assert len(result.iterations) == 3
    assert result.tool_calls_total == 3


def test_unknown_tool_error_feedback() -> None:
    # LLM 调未知工具 -> 错误回喂 -> LLM 给最终答案
    llm = FakeChatModel([
        AIMessage(content="", tool_calls=[_tc("nope", {}, "c1")]),
        AIMessage(content="抱歉无此工具"),
    ])
    loop = ReactLoop(max_iterations=5)
    result = loop.run("sys", [HumanMessage(content="x")], [add], llm)
    assert result.stopped_reason == "final_answer"
    assert result.iterations[0].tool_results[0].startswith("[error] 未知工具")


def test_no_tools() -> None:
    llm = FakeChatModel([AIMessage(content="无工具也行")])
    loop = ReactLoop()
    result = loop.run("sys", [HumanMessage(content="hi")], [], llm)
    assert result.content == "无工具也行"
    assert result.stopped_reason == "final_answer"


def test_context_builder_prepends_system() -> None:
    from careercrew_ai.react.context_builder import ContextBuilder

    convo = ContextBuilder().build("你是助手", [HumanMessage(content="hi")], memory_preamble="上次聊了 RAG")
    assert convo[0].content == "你是助手"
    assert "[相关记忆]" in convo[1].content
    assert convo[2].content == "hi"
