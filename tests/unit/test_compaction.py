"""compaction 基础版 + Pre-compaction Memory Flush 测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from careercrew_core.memory.compaction import Compactor
from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.semantic import SemanticFactStore


class FakeLLM:
    def invoke(self, prompt):
        return AIMessage(content="用户聊了大模型与 RAG，问过检索流程。")


def _long_messages(n: int) -> list:
    return [
        HumanMessage(content=f"这是第{i}条很长很长的对话内容，关于大模型应用与 RAG 技术。")
        for i in range(n)
    ]


def test_should_compact_over_threshold() -> None:
    c = Compactor(FakeLLM(), user_id="u1", token_threshold_ratio=0.5, retention_tokens=50)
    assert c.should_compact(_long_messages(30)) is True


def test_should_compact_under_threshold() -> None:
    c = Compactor(FakeLLM(), user_id="u1", token_threshold_ratio=0.9, retention_tokens=100000)
    assert c.should_compact(_long_messages(3)) is False


def test_compact_keeps_recent_and_writes_entry() -> None:
    c = Compactor(FakeLLM(), user_id="u1", token_threshold_ratio=0.5, retention_tokens=30)
    em = EpisodicMemory(FakeMemoryDb(), user_id="u1", thread_id="t1")
    msgs = _long_messages(20)
    new_msgs, entry = c.compact(msgs, em)
    # 保留区 + 压缩摘要
    assert len(new_msgs) <= len(msgs)
    assert any(isinstance(m, SystemMessage) and "压缩摘要" in str(m.content) for m in new_msgs)
    # compaction 条目写 JSONL，带 firstKeptEntryId
    assert entry is not None
    assert entry.type == "compaction"
    assert "firstKeptEntryId" in entry.content
    # 保留区原封（最后几条）
    assert new_msgs[-1].content == msgs[-1].content


def test_compact_under_threshold_noop() -> None:
    c = Compactor(FakeLLM(), user_id="u1", token_threshold_ratio=0.9, retention_tokens=100000)
    em = EpisodicMemory(FakeMemoryDb(), user_id="u1", thread_id="t1")
    msgs = _long_messages(3)
    new_msgs, entry = c.compact(msgs, em)
    assert new_msgs == msgs
    assert entry is None


def test_compact_flushes_to_semantic_facts() -> None:
    """M2: 压缩前 flush 关键信息到语义事实。"""
    class FlushLLM:
        def invoke(self, prompt):
            from langchain_core.messages import AIMessage
            return AIMessage(content='{"skills": ["Python", "RAG"], "target_companies": ["字节"], "preferences": {"salary_min": 30, "city": ["北京"]}}')

    db = FakeMemoryDb()
    um = SemanticFactStore(db, user_id="u1")
    c = Compactor(FlushLLM(), user_id="u1", token_threshold_ratio=0.5, retention_tokens=30,
                  user_model_store=um)
    em = EpisodicMemory(db, user_id="u1", thread_id="t1")
    c.compact(_long_messages(20), em)
    model = um.load("u1")
    assert "Python" in model.profile.skills
    assert model.target_companies == ["字节"]
    assert model.preferences.salary_min == 30
    assert "北京" in model.preferences.city


def test_compact_flush_failure_does_not_block() -> None:
    """M2: flush LLM 输出非法 JSON 时不阻塞压缩。"""
    class BadLLM:
        def invoke(self, prompt):
            from langchain_core.messages import AIMessage
            return AIMessage(content="不是 JSON，随便说")

    db = FakeMemoryDb()
    um = SemanticFactStore(db, user_id="u1")
    c = Compactor(BadLLM(), user_id="u1", token_threshold_ratio=0.5, retention_tokens=30,
                  user_model_store=um)
    em = EpisodicMemory(db, user_id="u1", thread_id="t1")
    new_msgs, entry = c.compact(_long_messages(20), em)
    assert entry is not None  # 压缩仍完成
    assert um.load("u1").profile.skills == []  # User Model 未写坏
