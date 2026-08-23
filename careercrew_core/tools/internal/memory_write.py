"""memory_write 工具：关键事件写情景记忆（Postgres/Fake 统一后端）。

工厂注入 episodic store + 可选向量索引。面试/投递/offer/匹配事件后调用，
自动 parentId 接链；写入前脱敏；vector_index 注入时同步索引（幂等 upsert）。
"""
from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.redaction import redact_content
from careercrew_core.memory.types import MemoryEntry
from careercrew_core.memory.vector_index import VectorIndex


def make_memory_write_tool(
    episodic: EpisodicMemory,
    vector_index: VectorIndex | None = None,
    memory_service=None,
    user_id: str | None = None,
) -> BaseTool:
    """构造 memory_write 工具（注入 episodic store + 可选向量索引）。"""

    @tool
    def memory_write(type: str, content: dict, parentId: str | None = None) -> str:
        """写情景记忆（面试 / 投递 / offer / 匹配事件），自动 parentId 接最新条目。

        Args:
            type: 事件类型（session_start / interview_qa / job_match / application / offer / note）。
            content: 事件内容（dict）。
            parentId: 父节点 id（不传则接最新条目，构成 append-only 链）。
        """
        try:
            if memory_service is not None:
                entry = memory_service.write_event(
                    user_id or episodic.user_id, type, redact_content(content),
                    thread_id=episodic.thread_id, parent_id=parentId,
                )
            else:
                entry = episodic.write(
                    MemoryEntry(type=type, content=redact_content(content), parentId=parentId)
                )
                if vector_index is not None:
                    try:
                        vector_index.index_entry(entry)
                    except Exception:
                        pass  # 向量索引失败不阻塞记忆写入
        except (PermissionError, ValueError) as exc:
            return f"[error] {exc}"
        return f"已写入情景记忆: id={entry.id}, parentId={entry.parentId}, type={entry.type}"

    return memory_write
