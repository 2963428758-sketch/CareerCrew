"""rag_query 工具（多模态 RAG）：封装 MultimodalSearch 供 agent 调用。

输出保持纯文本格式兼容（R8），图片路径以 ``[image: 绝对路径]`` 行附尾，
Web/CLI 渲染层识别展示，文本模型忽略。

``sink`` 参数用于来源标注：传入 callable 时，每次检索到的 QueryResult
都会回调一次（供知识库问答等场景收集结构化来源，前端可点击查看）。
``category`` 参数限定检索范围（resume / knowledge / interview），留空检索全部。
"""
from __future__ import annotations

from collections.abc import Callable

from langchain_core.tools import BaseTool, StructuredTool

from careercrew_ai.vector_store import QueryResult
from careercrew_core.rag.categories import category_label
from careercrew_core.rag.retrieval.multimodal_search import MultimodalSearch


def make_rag_query_tool(
    mm_search: MultimodalSearch,
    sink: Callable[[QueryResult], None] | None = None,
    categories: str | list[str] | None = None,
) -> BaseTool:
    """构造 rag_query 工具。categories 限定检索分类（str 或 list），None/空 = 检索全部。"""
    bound: list[str] = [categories] if isinstance(categories, str) else list(categories or [])
    scope = "、".join(category_label(c) for c in bound) if bound else "全部"
    desc = (
        f"检索知识库（检索范围：{scope}），返回相关文档片段与图片引用。\n"
        "Args:\n    query: 检索查询（如\"RAG 的检索流程\"）。\n"
        "    top_k: 返回条数。"
    )

    def _run(query: str, top_k: int = 5) -> str:
        filters = {"category": bound} if bound else None
        results = mm_search.search(query, top_k=top_k, filters=filters)
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

    return StructuredTool.from_function(
        func=_run,
        name="rag_query",
        description=desc,
    )
