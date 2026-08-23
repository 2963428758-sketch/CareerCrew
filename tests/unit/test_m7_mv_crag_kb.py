"""M7 multivector（Qdrant 原生 MAX_SIM）+ 知识库级 contextual 开关单元测试。"""
from __future__ import annotations

import pytest

from careercrew_ai.vector_store.base_vector_store import VectorRecord
from careercrew_ai.vector_store.colbert import ColBERTLocalReranker, ColBERTQdrantReranker
from careercrew_core.rag.pipeline_multimodal import MultimodalIngestionPipeline


def _settings(colbert_multivector: bool):
    from careercrew_core.state.settings import load_settings

    s = load_settings()
    s.vector_store.url = ":memory:"
    s.vector_store.colbert_multivector = colbert_multivector
    return s


def _mat(*rows) -> list[list[float]]:
    return [list(r) for r in rows]


# ── Qdrant multivector：建表/写入/服务端打分（:memory: 真实 client） ──

@pytest.mark.integration
def test_multivector_upsert_and_server_scoring() -> None:
    from careercrew_ai.vector_store.qdrant_store import QdrantStore

    store = QdrantStore(_settings(colbert_multivector=True), collection_name="mv_test")
    # 两篇文档：d1 与查询 token 同向，d2 正交
    cb1 = _mat((1.0, 0.0), (0.9, 0.1))
    cb2 = _mat((0.0, 1.0), (0.1, 0.9))
    store.upsert([
        VectorRecord(id="d1", dense=[1.0] * 1024, text="doc one",
                     metadata={"colbert": cb1}),
        VectorRecord(id="d2", dense=[0.5] * 1024, text="doc two",
                     metadata={"colbert": cb2}),
    ])
    scores = store.colbert_scores(_mat((1.0, 0.0)), ["d1", "d2"])
    assert scores["d1"] > scores.get("d2", float("-inf"))

    # multivector 模式下 colbert 不落 payload（避免字符串化）
    pt = store._client.scroll("mv_test", limit=10)[0]
    payloads = {p.payload.get("_id"): p.payload for p in pt}
    assert all("colbert" not in p for p in payloads.values())


@pytest.mark.integration
def test_legacy_collection_without_colbert_still_scores_missing() -> None:
    from careercrew_ai.vector_store.qdrant_store import QdrantStore

    store = QdrantStore(_settings(colbert_multivector=False), collection_name="plain_test")
    store.upsert([VectorRecord(id="a", dense=[1.0] * 1024, text="x")])
    scores = store.colbert_scores([[1.0, 0.0]], ["a"])   # 无 text_colbert 向量路
    assert scores == {}                                   # 不抛错、无分数


# ── Qdrant 版精排器 ──

class FakeEmb:
    def __init__(self, q):
        self._q = q

    def encode(self, texts):
        class Out:
            dense = None
            sparse = None
            colbert = [self._q]

        return Out()


class FakeQR:
    def __init__(self, rid):
        self.id = rid
        self.score = 0.5
        self.text = rid
        self.metadata = {}


def test_qdrant_reranker_orders_by_scores() -> None:
    class FakeStore:
        def colbert_scores(self, q_vecs, ids, filters=None):
            return {"b": 9.0, "a": 1.0}

    rr = ColBERTQdrantReranker(FakeEmb([[1.0, 0.0]]), FakeStore())
    out = rr.rerank("q", [FakeQR("a"), FakeQR("b")], top_k=2)
    assert [r.id for r in out] == ["b", "a"]


def test_qdrant_reranker_degrades_without_scorer() -> None:
    rr = ColBERTQdrantReranker(FakeEmb([[1.0]]), object())   # 无 colbert_scores 方法
    docs = [FakeQR("a"), FakeQR("b")]
    assert [d.id for d in rr.rerank("q", docs, top_k=2)] == ["a", "b"]


def test_local_reranker_ignores_string_colbert_payload() -> None:
    """回归护栏：payload 里被字符串化的 colbert 不再参与打分（稳定降级原序）。"""
    d1 = FakeQR("d1")
    d1.metadata = {"colbert": "[[1.0, 0.0]]"}                # 历史缺陷的字符串化形态
    rr = ColBERTLocalReranker(FakeEmb([[1.0, 0.0]]))
    assert [d.id for d in rr.rerank("q", [d1], top_k=1)] == ["d1"]  # 原序返回不抛错


# ── M 批次：contextual 知识库级开关 ──

from careercrew_api.runtime.heavy import _resolve_contextual  # noqa: E402


class _Chunking:
    def __init__(self, contextual, by_category=None):
        self.contextual = contextual
        self.contextual_by_category = by_category or {}


class _Rag:
    def __init__(self, chunking):
        self.chunking = chunking


class _S:
    def __init__(self, chunking):
        self.rag = _Rag(chunking)


def test_resolve_contextual_category_overrides_global() -> None:
    s = _S(_Chunking(False, {"interview": True, "misc": False}))
    assert _resolve_contextual(s, "interview") is True     # 分类覆盖全局关
    assert _resolve_contextual(s, "misc") is False         # 显式覆盖为关
    assert _resolve_contextual(s, "other") is False        # 未声明回落全局(关)
    s2 = _S(_Chunking(True))
    assert _resolve_contextual(s2, "any") is True          # 全局开且无覆盖


def test_pipeline_honors_per_category_contextual() -> None:
    """pipeline 按 ingest 时的 category 决定是否调用 contextualizer。"""

    class FakeContextualizer:
        def __init__(self):
            self.calls = 0

        def contextualize(self, chunk, doc_text):
            self.calls += 1
            return type("C", (), {"contextualized_text": f"[ctx]{chunk.text}"})()

    class FakeEmb:
        def encode(self, texts):
            import numpy as np

            class Out:
                dense = np.zeros((len(texts), 4))
                sparse = None
                colbert = None

            return Out()

    class FakeStore:
        def __init__(self):
            self.records = []

        def upsert(self, records):
            self.records.extend(records)

    ctxz = FakeContextualizer()
    pipe = MultimodalIngestionPipeline(
        FakeEmb(), FakeStore(), contextualizer=ctxz,
        contextual=False,                       # 全局关
        contextual_resolver=lambda c: c == "hot",
        colbert_store=False,
    )
    pipe.ingest_text("正文内容", source="a.md", category="hot")
    assert ctxz.calls == 1                      # hot 分类覆盖为开
    pipe.ingest_text("正文内容", source="b.md", category="cold")
    assert ctxz.calls == 1                      # cold 回落全局关，未再调用
