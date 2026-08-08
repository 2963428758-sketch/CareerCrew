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


def test_react_loop_streaming() -> None:
    """流式: stream_callback 收到逐 token, 结果正确, 用户不等。"""
    tokens: list[str] = []

    class FakeStreamLLM:
        def bind_tools(self, tools, **kwargs):
            return self

        def stream(self, messages):
            from langchain_core.messages import AIMessageChunk
            for part in ["流式", "输出", "测试"]:
                yield AIMessageChunk(content=part)

    loop = ReactLoop(max_iterations=3, stream_callback=lambda t: tokens.append(t))
    result = loop.run("sys", [HumanMessage(content="hi")], [], FakeStreamLLM())
    assert "".join(tokens) == "流式输出测试"
    assert result.content == "流式输出测试"
    assert result.stopped_reason == "final_answer"


def test_react_loop_streaming_with_tool_call() -> None:
    """流式 + 工具调用: 第一轮流式出 tool_call, 执行后第二轮流式出最终答案。"""
    tokens: list[str] = []

    class FakeStreamLLM:
        def __init__(self):
            self._n = 0

        def bind_tools(self, tools, **kwargs):
            return self

        def stream(self, messages):
            from langchain_core.messages import AIMessageChunk
            if self._n == 0:
                self._n += 1
                yield AIMessageChunk(
                    content="", tool_call_chunks=[
                        {"name": "add", "args": '{"a": 1, "b": 2}', "id": "c1", "index": 0, "type": "tool_call_chunk"},
                    ],
                )
            else:
                for part in ["结果", "是", "3"]:
                    yield AIMessageChunk(content=part)

    loop = ReactLoop(max_iterations=3, stream_callback=lambda t: tokens.append(t))
    result = loop.run("sys", [HumanMessage(content="算 1+2")], [add], FakeStreamLLM())
    assert result.stopped_reason == "final_answer"
    assert result.content == "结果是3"
    assert result.tool_calls_total == 1
    assert "".join(tokens) == "结果是3"
