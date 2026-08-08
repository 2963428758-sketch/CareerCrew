"""阶段 D 可视化 demo：自建 RAG 端到端。

跑法：conda run -n careercrew python scripts/demo_rag.py
展示：ingest data/knowledge/（BGE-M3 + Contextual Chunking + Milvus）
      -> HybridSearch（dense+sparse RRF）+ 硅基流动 rerank 检索
"""
from __future__ import annotations

from pathlib import Path

from careercrew_ai.embedding import create_embedding
from careercrew_ai.reranker import create_reranker
from careercrew_ai.vector_store import create_vector_store
from careercrew_core.rag.pipeline import IngestionPipeline
from careercrew_core.rag.retrieval.hybrid_search import HybridSearch
from careercrew_core.state.settings import load_settings


def main() -> None:
    settings = load_settings()
    kb_dir = Path("data/knowledge")
    files = sorted(kb_dir.glob("*.md"))
    print("=" * 64)
    print("阶段 D demo：自建 RAG（BGE-M3 + Contextual Chunking + Milvus + rerank）")
    print("=" * 64)
    print(f"LLM: {settings.llm.model} | Embedding: {settings.embedding.provider} | Rerank: {settings.rerank.backend}")

    embedding = create_embedding(settings)
    store = create_vector_store(settings)
    reranker = create_reranker(settings)

    # 1. ingest（KB 已入库则跳过，避免每次 contextual=True 重 ingest 全库过慢）
    if store.count() > 0:
        print(f"知识库已入库（{store.count()} chunks），跳过 ingest\n")
    else:
        print(f"\n--- 1) Ingest {len(files)} 知识库文档 ---")
        pipe = IngestionPipeline(
            embedding, store, contextual=False,
            chunk_size=settings.rag.chunking.chunk_size,
            chunk_overlap=settings.rag.chunking.chunk_overlap,
        )
        total = 0
        for f in files:
            n = pipe.ingest_file(f)
            print(f"  {f.name}: {n} chunks")
            total += n
        print(f"  共 {total} chunks 入库（collection={settings.vector_store.collections['knowledge']}）")

    # 2. 检索
    hs = HybridSearch(embedding, store, reranker=reranker, top_m=20)
    queries = ["RAG 怎么减少幻觉？", "为什么手写 ReAct 而不用 create_react_agent？", "append-only 记忆树有什么用？"]
    print("\n--- 2) HybridSearch（dense+sparse RRF）+ rerank 检索 ---")
    for q in queries:
        print(f"\n  Q: {q}")
        res = hs.search(q, top_k=2)
        for i, r in enumerate(res, 1):
            text_one_line = r.text[:90].replace("\n", " ")
            print(f"    [{i}] score={r.score:.3f} | {text_one_line}...")

    print("\n" + "=" * 64)
    print("RAG 闭环：ingest(BGE-M3+Contextual+Milvus) -> 检索(Hybrid+RRF) -> rerank(硅基流动)")
    print("=" * 64)


if __name__ == "__main__":
    main()
