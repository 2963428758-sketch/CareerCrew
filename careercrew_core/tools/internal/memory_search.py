"""memory_search 工具（I1）：情景记忆语义检索。

工厂注入 VectorIndex（无则 stub 兜底）。I1 前为占位 stub。
"""
from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from careercrew_core.memory.vector_index import VectorIndex


def make_memory_search_tool(vector_index: VectorIndex | None = None) -> BaseTool:
    """构造 memory_search 工具（注入向量索引；None 时 stub 兜底）。"""

    @tool
    def memory_search(query: str, top_k: int = 5) -> str:
        """检索情景记忆：按语义查找历史面试问答 / 投递 / offer 等事件。

        Args:
            query: 检索查询（如"上次的 RAG 面试题"）。
            top_k: 返回条数。
        """
        if vector_index is None:
            return f"[memory_search stub] query={query!r}, top_k={top_k}（未配置向量索引）"
        entries = vector_index.search(query, top_k=top_k)
        if not entries:
            return "（无相关记忆）"
        return "\n".join(f"[{e.type}] {e.content}" for e in entries)

    return memory_search
