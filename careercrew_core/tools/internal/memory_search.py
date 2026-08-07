"""memory_search 工具 stub（B5）。

I1 阶段接入 Milvus 情景记忆向量检索；当前返回占位串，供工具注册表 / ReAct 循环跑通。
"""
from __future__ import annotations

from langchain_core.tools import tool


@tool
def memory_search(query: str, top_k: int = 5) -> str:
    """检索情景记忆：按语义查找历史面试问答 / 投递 / offer 等事件。

    Args:
        query: 检索查询（如"上次的 RAG 面试题"）。
        top_k: 返回条数。

    Returns:
        命中的情景记忆条目（I1 阶段接入 Milvus 检索；当前为 stub）。
    """
    return f"[memory_search stub] query={query!r}, top_k={top_k}（I1 阶段接入 Milvus 检索）"
