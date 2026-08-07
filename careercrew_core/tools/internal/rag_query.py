"""rag_query 工具（D4）：封装 HybridSearch 供 agent 调用。

工厂注入 HybridSearch（含 embedding/store/reranker）。
"""
from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from careercrew_core.rag.retrieval.hybrid_search import HybridSearch


def make_rag_query_tool(hybrid_search: HybridSearch) -> BaseTool:
    """构造 rag_query 工具。"""

    @tool
    def rag_query(query: str, top_k: int = 5) -> str:
        """检索知识库（八股 / 面经 / JD / 简历范本），返回相关文档片段。

        Args:
            query: 检索查询（如"RAG 的检索流程"）。
            top_k: 返回条数。
        """
        results = hybrid_search.search(query, top_k=top_k)
        if not results:
            return "（无检索结果）"
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] (score={r.score:.3f}) {r.text}")
        return "\n".join(lines)

    return rag_query
