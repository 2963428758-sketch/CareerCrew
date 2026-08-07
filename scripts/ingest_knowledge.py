"""知识库摄取（D4）：把 data/knowledge/ 下文档 ingest 到 Milvus。

跑法：conda run -n careercrew python scripts/ingest_knowledge.py [data/knowledge/]
流程：load -> split -> Contextual Chunking(LLM) -> BGE-M3 encode -> Milvus upsert
"""
from __future__ import annotations

import sys
from pathlib import Path

from careercrew_ai.embedding import create_embedding
from careercrew_ai.llm import create_llm
from careercrew_ai.vector_store import create_vector_store
from careercrew_core.rag.chunking.contextualizer import Contextualizer
from careercrew_core.rag.pipeline import IngestionPipeline
from careercrew_core.state.settings import load_settings


def main() -> None:
    settings = load_settings()
    kb_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/knowledge")
    files = sorted([*kb_dir.glob("**/*.md"), *kb_dir.glob("**/*.txt")])
    if not files:
        print(f"无文档可摄取（{kb_dir}）")
        return

    print(f"LLM: {settings.llm.model} | Embedding: {settings.embedding.provider} | Store: {settings.vector_store.backend}")
    print(f"待摄取 {len(files)} 个文档...")

    embedding = create_embedding(settings)
    store = create_vector_store(settings)
    contextualizer = None
    if settings.rag.chunking.contextual:
        llm = create_llm(settings, max_tokens=256)
        contextualizer = Contextualizer(llm)

    pipe = IngestionPipeline(
        embedding, store, contextualizer=contextualizer,
        contextual=settings.rag.chunking.contextual,
        chunk_size=settings.rag.chunking.chunk_size,
        chunk_overlap=settings.rag.chunking.chunk_overlap,
    )

    total = 0
    for f in files:
        n = pipe.ingest_file(f)
        print(f"  {f}: {n} chunks")
        total += n
    print(f"摄取完成：{len(files)} 文档，{total} chunks -> Milvus collection {settings.vector_store.collections['knowledge']}")


if __name__ == "__main__":
    main()
