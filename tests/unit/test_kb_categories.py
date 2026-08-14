"""知识库分类单测：文件名识别 + rag_query 分类过滤。"""
from __future__ import annotations

from careercrew_ai.vector_store import QueryResult
from careercrew_core.rag.categories import (
    CATEGORY_INTERVIEW,
    CATEGORY_JOB,
    CATEGORY_KNOWLEDGE,
    CATEGORY_RESUME,
    categories_for_agent,
    category_for_doc,
)
from careercrew_core.tools.internal.rag_query import make_rag_query_tool


def test_category_for_doc() -> None:
    assert category_for_doc("求职简历") == CATEGORY_RESUME
    assert category_for_doc("我的resume") == CATEGORY_RESUME
    assert category_for_doc("尚硅谷-05-Tools") == CATEGORY_KNOWLEDGE
    assert category_for_doc("langchain_v1_tools") == CATEGORY_KNOWLEDGE
    assert category_for_doc("面试题汇总") == CATEGORY_INTERVIEW
    assert category_for_doc("大厂面经") == CATEGORY_INTERVIEW
    assert category_for_doc("字节跳动JD") == CATEGORY_JOB
    assert category_for_doc("目标岗位汇总") == CATEGORY_JOB
    assert category_for_doc("company_jobs") == CATEGORY_JOB
    assert category_for_doc("") == CATEGORY_KNOWLEDGE


class FakeHS:
    def __init__(self) -> None:
        self.last_filters = None

    def search(self, query, top_k=5, filters=None):
        self.last_filters = filters
        return [QueryResult(id="a", score=0.9, text="x", metadata={"doc": "d"})]


def test_rag_query_category_filter() -> None:
    hs = FakeHS()
    t = make_rag_query_tool(hs, categories="resume")
    t.invoke({"query": "学校", "top_k": 3})
    assert hs.last_filters == {"category": ["resume"]}


def test_rag_query_multi_category_filter() -> None:
    """面试官绑定多分类：filters 传 list，Qdrant 端走 MatchAny。"""
    hs = FakeHS()
    t = make_rag_query_tool(hs, categories=[CATEGORY_INTERVIEW, CATEGORY_RESUME])
    t.invoke({"query": "RAG 八股", "top_k": 3})
    assert hs.last_filters == {"category": [CATEGORY_INTERVIEW, CATEGORY_RESUME]}


def test_rag_query_no_category_no_filter() -> None:
    hs = FakeHS()
    t = make_rag_query_tool(hs)
    t.invoke({"query": "学校", "top_k": 3})
    assert hs.last_filters is None


def test_categories_for_agent() -> None:
    """每个 agent 的 rag_query 只检索对应分类（面试官多分类）。"""
    assert categories_for_agent("matcher") == CATEGORY_JOB
    assert categories_for_agent("resume") == CATEGORY_RESUME
    assert categories_for_agent("interviewer") == [CATEGORY_INTERVIEW, CATEGORY_RESUME]
    assert categories_for_agent("salary") == CATEGORY_JOB
    assert categories_for_agent("planner") == CATEGORY_KNOWLEDGE
    assert categories_for_agent("knowledge") is None  # 用户选择器控制，不过滤
    assert categories_for_agent("unknown") is None
