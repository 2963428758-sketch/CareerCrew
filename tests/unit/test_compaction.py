"""I2-I4 compaction 基础版测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from careercrew_core.memory.compaction import Compactor
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.user_model import UserModelStore


class FakeLLM:
    def invoke(self, prompt):
        from langchain_core.messages import AIMessage
        return AIMessage(content="用户聊了大模型与 RAG，问过检索流程。")


def _long_messages(n: int) -> list:
    return [HumanMessage(content="这是第%d条很长很长的对话内容，关于大模型应用与 RAG 技术。" % i) for i in range(n)]


def test_should_compact_over_threshold() -> None:
    c = Compactor(FakeLLM(), token_threshold_ratio=0.5, retention_tokens=50)
    assert c.should_compact(_long_messages(30)) is True


def test_should_compact_under_threshold() -> None:
    c = Compactor(FakeLLM(), token_threshold_ratio=0.9, retention_tokens=100000)
    assert c.should_compact(_long_messages(3)) is False


def test_compact_keeps_recent_and_writes_entry(tmp_path) -> None:
    c = Compactor(FakeLLM(), token_threshold_ratio=0.5, retention_tokens=30)
    em = EpisodicMemory(tmp_path / "t.jsonl")
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


def test_compact_under_threshold_noop(tmp_path) -> None:
    c = Compactor(FakeLLM(), token_threshold_ratio=0.9, retention_tokens=100000)
    em = EpisodicMemory(tmp_path / "t.jsonl")
    msgs = _long_messages(3)
    new_msgs, entry = c.compact(msgs, em)
    assert new_msgs == msgs
    assert entry is None


def test_compact_flushes_to_user_model(tmp_path) -> None:
    """M2: 压缩前 flush 关键信息到 User Model。"""
    class FlushLLM:
        def invoke(self, prompt):
            from langchain_core.messages import AIMessage
            return AIMessage(content='{"skills": ["Python", "RAG"], "target_companies": ["字节"], "preferences": {"salary_min": 30, "city": ["北京"]}}')

    um = UserModelStore(tmp_path / "um.json")
    c = Compactor(FlushLLM(), token_threshold_ratio=0.5, retention_tokens=30,
                  user_model_store=um, user_id="u1")
    em = EpisodicMemory(tmp_path / "t.jsonl")
    c.compact(_long_messages(20), em)
    model = um.load("u1")
    assert "Python" in model.profile.skills
    assert model.target_companies == ["字节"]
    assert model.preferences.salary_min == 30
    assert "北京" in model.preferences.city


def test_compact_flush_failure_does_not_block(tmp_path) -> None:
    """M2: flush LLM 输出非法 JSON 时不阻塞压缩。"""
    class BadLLM:
        def invoke(self, prompt):
            from langchain_core.messages import AIMessage
            return AIMessage(content="不是 JSON，随便说")

    um = UserModelStore(tmp_path / "um.json")
    c = Compactor(BadLLM(), token_threshold_ratio=0.5, retention_tokens=30,
                  user_model_store=um, user_id="u1")
    em = EpisodicMemory(tmp_path / "t.jsonl")
    new_msgs, entry = c.compact(_long_messages(20), em)
    assert entry is not None  # 压缩仍完成
    assert um.load("u1").profile.skills == []  # User Model 未写坏
