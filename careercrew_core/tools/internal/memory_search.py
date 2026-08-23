"""memory_search 工具（读路径通道二）：语义事实（LLM 路由）+ 情景事件（向量）融合检索。

工厂注入 SemanticFactStore + MemoryRouter + VectorIndex；缺组件时降级
为可用部分，全部缺失时 stub 兜底。
"""
from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from careercrew_core.memory.router import MemoryRouter
from careercrew_core.memory.semantic import SemanticFactStore
from careercrew_core.memory.vector_index import VectorIndex


def make_memory_search_tool(
    vector_index: VectorIndex | None = None,
    fact_store: SemanticFactStore | None = None,
    router: MemoryRouter | None = None,
    memory_service=None,
    user_id: str | None = None,
) -> BaseTool:
    """构造 memory_search 工具（注入向量索引 / 事实库 / 路由；缺失时降级）。"""

    @tool
    def memory_search(query: str, top_k: int = 5) -> str:
        """检索用户记忆：语义事实（技能/偏好/目标公司）+ 历史事件（面试/投递/offer）。

        Args:
            query: 检索查询（如"上次的 RAG 面试题"）。
            top_k: 返回条数。
        """
        if memory_service is not None:
            rows = memory_service.search(user_id or "", query, limit=top_k)
            if not rows:
                return "（无相关记忆）"
            return "\n".join(
                f"[{row['kind']}:{row['type']}] {row.get('description') or row.get('content')}"
                for row in rows
            )
        if vector_index is None and fact_store is None:
            return f"[memory_search stub] query={query!r}, top_k={top_k}（未配置记忆检索）"
        lines: list[str] = []
        if fact_store is not None and router is not None:
            facts = router.select(query, fact_store.list_facts())
            for f in facts:
                lines.append(f"[fact:{f.type}] {f.description or f.name}: {f.content}")
        if vector_index is not None:
            try:
                for e in vector_index.search(query, top_k=top_k):
                    lines.append(f"[{e.type}] {e.content}")
            except Exception:
                pass
        return "\n".join(lines) if lines else "（无相关记忆）"

    return memory_search
