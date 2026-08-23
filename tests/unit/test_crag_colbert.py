"""M7 ColBERT MaxSim 精排 + M5 CRAG 评估-纠错环单元测试。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from careercrew_ai.vector_store.colbert import ColBERTLocalReranker, max_sim_score
from careercrew_core.rag.retrieval.retrieval_assessor import (
    RetrievalAssessor,
    _parse_verdict,
    assess,
)
from tests.fakes import FakeChatModel

# ── M7:MaxSim 纯函数 ──

def test_max_sim_identical_vectors_max_score() -> None:
    q = [[1.0, 0.0], [0.0, 1.0]]
    assert max_sim_score(q, [[1.0, 0.0], [0.0, 1.0]]) == pytest.approx(2.0)


def test_max_sim_orthogonal_zero() -> None:
    q = [[1.0, 0.0]]
    d = [[0.0, 1.0]]
    assert max_sim_score(q, d) == pytest.approx(0.0)


def test_max_sim_empty_inputs() -> None:
    assert max_sim_score([], [[1.0]]) == 0.0
    assert max_sim_score([[1.0]], []) == 0.0


class FakeQR:
    """QueryResult 协议桩（metadata 携带 colbert 矩阵）。"""

    def __init__(self, rid: str, colbert=None):
        self.id = rid
        self.score = 0.5
        self.text = f"doc {rid}"
        self.metadata = {"colbert": colbert} if colbert is not None else {}


class FakeEmb:
    def __init__(self, q_colbert):
        self._q = q_colbert

    def encode(self, texts):
        class Out:
            dense = None
            sparse = None
            colbert = [self._q]

        return Out()


def test_colbert_reranker_orders_by_maxsim() -> None:
    q = [[1.0, 0.0]]
    good = FakeQR("good", colbert=[[0.9, 0.1]])
    bad = FakeQR("bad", colbert=[[0.0, 1.0]])
    none = FakeQR("none")                      # 无 colbert 数据 -> 尾部降级
    rr = ColBERTLocalReranker(FakeEmb(q))
    out = rr.rerank("q", [bad, none, good], top_k=3)
    assert [r.id for r in out] == ["good", "bad", "none"]


def test_colbert_reranker_falls_back_on_encode_failure() -> None:
    class BoomEmb:
        def encode(self, texts):
            raise RuntimeError("model missing")

    docs = [FakeQR("a"), FakeQR("b")]
    rr = ColBERTLocalReranker(BoomEmb())
    assert [d.id for d in rr.rerank("q", docs, top_k=2)] == ["a", "b"]


# ── M5:CRAG ──

class Doc:
    def __init__(self, rid: str, text: str):
        self.id = rid
        self.text = text
        self.score = 0.9


def test_parse_verdict_json_extraction() -> None:
    ok = _parse_verdict('前言 {"verdict": "incorrect", "rewritten_query": "RAG 融合"} 后记')
    assert ok["verdict"] == "incorrect" and "融合" in ok["rewritten_query"]
    bad = _parse_verdict("不是 JSON")
    assert bad["verdict"] == "ambiguous"


def test_assess_empty_docs_is_incorrect() -> None:
    llm = FakeChatModel([AIMessage(content='{"verdict": "correct"}')])
    assert assess("q", [], llm)["verdict"] == "incorrect"


def test_assessor_rewrites_on_incorrect_and_merges() -> None:
    # 第一次评估 incorrect 并给改写；第二次 correct 停止
    llm = FakeChatModel([
        AIMessage(content='{"verdict": "incorrect", "rewritten_query": "BGE-M3 混合检索 RRF"}'),
        AIMessage(content='{"verdict": "correct"}'),
    ])
    searches: list[str] = []

    def search_fn(q: str):
        searches.append(q)
        if len(searches) == 1:
            return [Doc("d1", "偏题片段")]
        return [Doc("d1", "偏题片段"), Doc("d2", "RRF 融合细节")]

    assessor = RetrievalAssessor(llm, search_fn)
    docs, meta = assessor.run("RAG 怎么做", top_k=5)
    assert searches == ["RAG 怎么做", "BGE-M3 混合检索 RRF"]
    assert [d.id for d in docs] == ["d1", "d2"]      # 合并去重
    assert meta["trail"] == ["incorrect", "correct"]


def test_assessor_stops_when_rewrite_same_as_query() -> None:
    llm = FakeChatModel([
        AIMessage(content='{"verdict": "incorrect", "rewritten_query": "同一查询"}'),
    ])
    searches: list[str] = []

    def search_fn(q: str):
        searches.append(q)
        return [Doc("d1", "x")]

    RetrievalAssessor(llm, search_fn).run("同一查询", top_k=3)
    assert searches == ["同一查询"]                  # 改写无意义即不重检
