"""上下文自动压缩中间件测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from careercrew_ai.agents.langchain_agent import (
    ContextCompactionMiddleware,
    _estimate_msg_tokens,
    build_agent,
)


class FakeLLM:
    def invoke(self, prompt):
        return AIMessage(content="用户聊了大模型与 RAG。")


def _long_messages(n: int) -> list:
    return [
        HumanMessage(content=f"第{i}条很长很长的对话内容，关于大模型应用与 RAG 技术。")
        for i in range(n)
    ]


def test_under_threshold_no_compaction() -> None:
    mw = ContextCompactionMiddleware(
        FakeLLM(), token_threshold_ratio=0.9, retention_tokens=100000
    )
    msgs = _long_messages(3)
    assert mw.before_model({"messages": msgs}, None) is None


def test_over_threshold_compacts_old_messages() -> None:
    mw = ContextCompactionMiddleware(
        FakeLLM(), token_threshold_ratio=0.5, retention_tokens=30
    )
    msgs = _long_messages(20)
    out = mw.before_model({"messages": msgs}, None)
    assert out is not None
    new_msgs = out["messages"]
    # 保留了最近消息 + 压缩摘要
    assert any(isinstance(m, SystemMessage) and "压缩摘要" in str(m.content) for m in new_msgs)
    assert new_msgs[-1].content == msgs[-1].content  # 保留区原封


def test_compaction_grace_prevents_repeated_compaction() -> None:
    """回归：压缩一次后，宽限期内的后续模型调用不再重复压缩（ReAct 每轮都过线时）。"""
    calls: list[str] = []

    class RecordingLLM:
        def invoke(self, prompt):
            calls.append(prompt)
            return AIMessage(content="摘要")

    mw = ContextCompactionMiddleware(
        RecordingLLM(), token_threshold_ratio=0.5, retention_tokens=30
    )
    msgs = _long_messages(20)
    assert mw.before_model({"messages": msgs}, None) is not None  # 第 1 次真正压缩
    assert mw.before_model({"messages": msgs}, None) is None       # 宽限期内不再压缩
    assert mw.before_model({"messages": msgs}, None) is None
    assert len(calls) == 1


def test_compaction_failure_falls_back() -> None:
    class BadLLM:
        def invoke(self, prompt):
            raise RuntimeError("llm down")

    mw = ContextCompactionMiddleware(
        BadLLM(), token_threshold_ratio=0.5, retention_tokens=30
    )
    msgs = _long_messages(20)
    assert mw.before_model({"messages": msgs}, None) is None  # 不阻塞


def test_build_agent_accepts_extra_middleware() -> None:
    from tests.fakes import FakeChatModel

    agent = build_agent(
        llm=FakeChatModel([AIMessage(content="ok")]),
        tools=None,
        system_prompt="test",
        max_iterations=3,
        extra_middleware=[
            ContextCompactionMiddleware(
                FakeLLM(), token_threshold_ratio=0.5, retention_tokens=30
            )
        ],
    )
    assert agent is not None


def test_estimate_ignores_usage_metadata_input_tokens() -> None:
    """回归：usage_metadata.input_tokens 是整次上下文 token 数，不能当作单条消息大小，
    否则一条空消息会被估成数万 token、单独分块触发空摘要调用。"""
    msg = AIMessage(
        content="",
        usage_metadata={"input_tokens": 58604, "output_tokens": 100, "total_tokens": 58704},
    )
    assert _estimate_msg_tokens(msg) == 4  # 空内容按内容长度估算


def test_summarize_skips_all_empty_chunk() -> None:
    """回归：纯工具调用消息（content=""）单独成 chunk 时直接跳过，不再浪费一次 LLM 调用。"""
    calls: list[str] = []

    class RecordingLLM:
        def invoke(self, prompt):
            calls.append(prompt)
            return AIMessage(content="摘要")

    mw = ContextCompactionMiddleware(RecordingLLM(), token_threshold_ratio=0.5, retention_tokens=30)
    summary = mw._summarize([
        AIMessage(content="", tool_calls=[{"name": "rag_query", "args": {}, "id": "1", "type": "tool_call"}]),
    ])
    assert summary == ""
    assert calls == []


def test_summarize_skips_empty_lines_within_chunk() -> None:
    """回归：chunk 内混有空消息时，摘要 prompt 不含"AIMessage:"空行。"""
    calls: list[str] = []

    class RecordingLLM:
        def invoke(self, prompt):
            calls.append(prompt)
            return AIMessage(content="摘要")

    mw = ContextCompactionMiddleware(RecordingLLM(), token_threshold_ratio=0.5, retention_tokens=30)
    mw._summarize([
        HumanMessage(content="什么是langchain"),
        AIMessage(content="", tool_calls=[{"name": "rag_query", "args": {}, "id": "1", "type": "tool_call"}]),
    ])
    assert len(calls) == 1
    assert "AIMessage:" not in calls[0]
    assert "HumanMessage: 什么是langchain" in calls[0]
