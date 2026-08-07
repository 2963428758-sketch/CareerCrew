"""C4 短期 Context Window 管理测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from careercrew_core.memory.short_term import ShortTermMemory, estimate_tokens


def test_estimate_tokens_positive() -> None:
    msgs = [HumanMessage(content="hello world")]
    assert estimate_tokens(msgs) > 0


def test_trim_under_budget_unchanged() -> None:
    stm = ShortTermMemory(max_tokens=1000)
    msgs = [HumanMessage(content="hi"), AIMessage(content="hello")]
    assert stm.trim(msgs) == msgs


def test_trim_keeps_recent() -> None:
    stm = ShortTermMemory(max_tokens=10)  # 很小，触发截断
    msgs = [
        HumanMessage(content="a" * 60),
        AIMessage(content="b" * 60),
        HumanMessage(content="recent"),
    ]
    trimmed = stm.trim(msgs)
    assert trimmed[-1].content == "recent"  # 保留最近
    assert len(trimmed) < len(msgs)  # 截断了旧的


def test_trim_keeps_at_least_one() -> None:
    stm = ShortTermMemory(max_tokens=1)
    msgs = [HumanMessage(content="a" * 100), AIMessage(content="b" * 100)]
    trimmed = stm.trim(msgs)
    assert len(trimmed) >= 1  # 至少留最近 1 条


def test_append() -> None:
    stm = ShortTermMemory()
    out = stm.append([HumanMessage(content="hi")], AIMessage(content="hello"))
    assert len(out) == 2
