"""M4 Agentic RAG 测试：router / decomposer / AgenticSearch 融合。"""
from __future__ import annotations

from langchain_core.messages import AIMessage

from careercrew_ai.vector_store import QueryResult
from careercrew_core.rag.agent_router import QueryRouter
from careercrew_core.rag.agentic_search import AgenticSearch
from careercrew_core.rag.query_decomposer import QueryDecomposer


def test_router_memory_keyword() -> None:
    assert QueryRouter().route("上次的 RAG 面试题") == "memory"
    assert QueryRouter().route("我投过哪些公司") == "memory"


def test_router_web_keyword() -> None:
    assert QueryRouter().route("今年大模型岗位薪资行情") == "web"


def test_router_default_kb() -> None:
    assert QueryRouter().route("讲讲 RAG 的检索流程") == "kb"


def test_router_llm() -> None:
    class FakeLLM:
        def invoke(self, prompt):
            return AIMessage(content="web")

    assert QueryRouter().route_llm("最新薪资", FakeLLM()) == "web"


def test_decompose_single() -> None:
    class FakeLLM:
        def invoke(self, prompt):
            return AIMessage(content="什么是 RAG")

    assert QueryDecomposer().decompose("什么是 RAG", FakeLLM()) == ["什么是 RAG"]


def test_decompose_multi() -> None:
    class FakeLLM:
        def invoke(self, prompt):
            return AIMessage(content="RAG 怎么减少幻觉\nAgent 怎么调工具")

    d = QueryDecomposer().decompose("RAG 和 Agent 的关系", FakeLLM())
    assert len(d) == 2


class _FakeHybrid:
    def __init__(self):
        self.calls = []

    def search(self, query, top_k=5):
        self.calls.append(query)
        return [QueryResult(id=f"{query}#0", score=0.9, text=query, metadata={})]


def test_agentic_search_multi_hop_fuses() -> None:
    """多跳: 分解成 2 个子查询 + 主查询 -> rrf_fuse 融合。"""
    class FakeLLM:
        def invoke(self, prompt):
            return AIMessage(content="RAG 怎么减少幻觉\nAgent 怎么调工具")

    hybrid = _FakeHybrid()
    agentic = AgenticSearch(hybrid, decomposer=QueryDecomposer(), llm=FakeLLM())
    res = agentic.search("RAG 和 Agent 的关系", top_k=3)
    # 主查询 + 2 子查询都被检索
    assert len(hybrid.calls) == 3
    assert len(res) == 3  # rrf_fuse 后 3 个结果（各查询 1 个）


def test_agentic_search_single_hop_no_fuse() -> None:
    class FakeLLM:
        def invoke(self, prompt):
            return AIMessage(content="RAG 怎么减少幻觉")

    hybrid = _FakeHybrid()
    agentic = AgenticSearch(hybrid, decomposer=QueryDecomposer(), llm=FakeLLM())
    res = agentic.search("RAG 怎么减少幻觉", top_k=3)
    assert len(hybrid.calls) == 1  # 只检索主查询
    assert len(res) == 1


def test_agentic_search_memory_route() -> None:
    """memory 路由 -> memory_search。"""
    hybrid = _FakeHybrid()
    mem = lambda q, top_k=5: [QueryResult(id="mem1", score=0.9, text="上次面试字节", metadata={})]
    agentic = AgenticSearch(hybrid, memory_search=mem)
    res = agentic.search("上次的面试怎么样", top_k=3)
    assert res[0].id == "mem1"
    assert hybrid.calls == []  # 未走 kb
