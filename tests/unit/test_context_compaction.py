"""上下文自动压缩中间件测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from careercrew_ai.agents.langchain_agent import (
    ContextCompactionMiddleware,
    _estimate_msg_tokens,
    build_agent,
)


def test_estimate_cjk_counts_one_token_per_char() -> None:
    """回归（流式慢根因）：中文按 len//4 估算会低估 3~4 倍，导致压缩阈值
    永不触发、上下文膨胀到单次调用 6万~20万 真实 token。CJK 字符必须按
    ~1 token/字 计。"""
    chinese = "这是一段用于估算测试的中文内容" * 100  # 1500 个 CJK 字符
    est = _estimate_msg_tokens(HumanMessage(content=chinese))
    assert est >= 1400  # 不能再是 1500//4≈375 的量级

    english = "a" * 400
    assert _estimate_msg_tokens(HumanMessage(content=english)) <= 108  # 英文维持 /4 口径


def test_realistic_chinese_history_triggers_compaction() -> None:
    """端到端回归：6 万字中文历史（真实约 5 万+ token）必须触发压缩。

    旧估算器下该历史被估成 ~1.5 万 token（低于 2 万阈值），压缩从未发生，
    实测单次模型调用输入达 16 万真实 token、耗时 139s。
    """
    calls: list[str] = []

    class RecordingLLM:
        def invoke(self, prompt):
            calls.append(prompt)
            return AIMessage(content="摘要")

    # retention=20000/ratio=0.7 → 阈值 20000；旧估算：60000/4*20条≈远超？——
    # 用与实测同量级的体量：10 轮 × (用户 500 字 + 回答 3000 字) ≈ 3.5 万字
    msgs = []
    for i in range(10):
        msgs.append(HumanMessage(content="问题" + "背景描述" * 250))
        msgs.append(AIMessage(content=f"报告{i}" + "分析结论内容" * 430))
    total_est = sum(_estimate_msg_tokens(m) for m in msgs)
    assert total_est > 20000, "测试前提：新估算器下应过阈值"

    mw = ContextCompactionMiddleware(RecordingLLM(), retention_tokens=20000)
    out = mw.before_model({"messages": msgs}, None)
    assert out is not None, "3.5万字中文历史必须触发压缩（旧估算器漏判）"
    new_msgs = out["messages"]
    assert isinstance(new_msgs[0], SystemMessage) and "压缩摘要" in str(new_msgs[0].content)
    assert sum(_estimate_msg_tokens(m) for m in new_msgs) < total_est


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
    # 压缩摘要以 SystemMessage 置顶；CJK 感知估算下中文按 ~1 token/字 计，
    # retention=30 甚至容不下单条消息（每条约 30 token），允许全部进摘要
    assert isinstance(new_msgs[0], SystemMessage) and "压缩摘要" in str(new_msgs[0].content)


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
    assert _estimate_msg_tokens(msg) == 8  # 空内容只算固定基线，与 usage 无关


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
