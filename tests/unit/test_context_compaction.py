"""上下文自动压缩中间件测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from careercrew_ai.agents.langchain_agent import (
    ContextCompactionMiddleware,
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
