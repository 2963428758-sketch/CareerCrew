"""rag_query 工具（多模态 RAG）：封装 MultimodalSearch 供 agent 调用。

输出保持纯文本格式兼容（R8），图片路径以 ``[image: 绝对路径]`` 行附尾，
Web/CLI 渲染层识别展示，文本模型忽略。

``sink`` 参数用于来源标注：传入 callable 时，每次检索到的 QueryResult
都会回调一次（供知识库问答等场景收集结构化来源，前端可点击查看）。
"""
from __future__ import annotations

from collections.abc import Callable

from langchain_core.tools import BaseTool, tool

from careercrew_ai.vector_store import QueryResult
from careercrew_core.rag.retrieval.multimodal_search import MultimodalSearch


def make_rag_query_tool(
    mm_search: MultimodalSearch,
    sink: Callable[[QueryResult], None] | None = None,
) -> BaseTool:
    """构造 rag_query 工具。"""

    @tool
    def rag_query(query: str, top_k: int = 5) -> str:
        """检索知识库（八股 / 面经 / JD / 简历范本），返回相关文档片段与图片引用。

        Args:
            query: 检索查询（如"RAG 的检索流程"）。
            top_k: 返回条数。
        """
        results = mm_search.search(query, top_k=top_k)
        if not results:
            return "（无检索结果）"
        lines = []
        for i, r in enumerate(results, 1):
            if sink is not None:
                sink(r)
            lines.append(f"[{i}] (score={r.score:.3f}) {r.text}")
            if r.image_path:
                lines.append(f"[image: {r.image_path}]")
        return "\n".join(lines)

    return rag_query
