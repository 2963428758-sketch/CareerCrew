"""memory_write 工具（C6）：关键事件写情景记忆。

工厂注入 episodic store。面试/投递/offer/匹配事件后调用，自动 parentId 接链。
"""
from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.types import MemoryEntry


def make_memory_write_tool(episodic: EpisodicMemory) -> BaseTool:
    """构造 memory_write 工具（注入 episodic store）。"""

    @tool
    def memory_write(type: str, content: dict, parentId: str | None = None) -> str:
        """写情景记忆（面试 / 投递 / offer / 匹配事件），自动 parentId 接最新条目。

        Args:
            type: 事件类型（session_start / interview_qa / job_match / application / offer / note）。
            content: 事件内容（dict）。
            parentId: 父节点 id（不传则接最新条目，构成 append-only 链）。
        """
        entry = episodic.write(MemoryEntry(type=type, content=content, parentId=parentId))
        return f"已写入情景记忆: id={entry.id}, parentId={entry.parentId}, type={entry.type}"

    return memory_write
