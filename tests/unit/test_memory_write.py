"""memory_write 工具测试（FakeMemoryDb 后端）。"""
from __future__ import annotations

from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.types import MemoryEntry
from careercrew_core.tools.internal.memory_write import make_memory_write_tool


def test_memory_write_tool_auto_chain() -> None:
    em = EpisodicMemory(FakeMemoryDb(), user_id="u1", thread_id="t1")
    t = make_memory_write_tool(em)
    out = t.invoke({"type": "interview_qa", "content": {"q": "q1", "a": "a1", "score": 8}})
    assert "已写入" in out
    assert "id=e_001" in out
    # 第二条：parentId 自动接 e_001
    out2 = t.invoke({"type": "job_match", "content": {"company": "字节"}})
    assert "parentId=e_001" in out2
    # 验证落盘
    entries = em._read_all()
    assert len(entries) == 2
    assert entries[0].id == "e_001" and entries[0].parentId is None
    assert entries[1].id == "e_002" and entries[1].parentId == "e_001"


def test_memory_write_tool_explicit_parent() -> None:
    em = EpisodicMemory(FakeMemoryDb(), user_id="u1", thread_id="t1")
    em.write(MemoryEntry(type="session_start", content="s"))  # e_001
    t = make_memory_write_tool(em)
    out = t.invoke({"type": "note", "content": {"x": 1}, "parentId": "e_001"})
    assert "parentId=e_001" in out
    assert em.latest().id == "e_002"


def test_memory_write_tool_redacts_secrets() -> None:
    em = EpisodicMemory(FakeMemoryDb(), user_id="u1", thread_id="t1")
    t = make_memory_write_tool(em)
    t.invoke({"type": "note", "content": {"token": "sk-abcdef1234567890", "phone": "13800138000"}})
    entry = em.latest()
    assert "[REDACTED]" in str(entry.content)
    assert "sk-abcdef1234567890" not in str(entry.content)
