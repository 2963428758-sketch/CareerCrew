"""知识库摄取（多模态 RAG）：文档 -> Qdrant。

跑法：conda run -n careercrew python scripts/ingest_knowledge.py [路径...]
默认语料：data/uploads/*.pdf/png/docx（data/knowledge 不参与知识库）
流程：
- md/txt：Markdown 直读 -> 切分 -> Contextual Chunking -> BGE-M3 -> Qdrant
- PDF/图片：MinerU 解析 -> 页面/对象文本 -> BGE-M3 -> Qdrant
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

from careercrew_ai.embedding import create_embedding
from careercrew_ai.llm import create_llm
from careercrew_ai.vector_store import create_vector_store
from careercrew_core.rag.chunking.contextualizer import Contextualizer
from careercrew_core.rag.loaders.mineru_loader import ParsingError
from careercrew_core.rag.pipeline_multimodal import MultimodalIngestionPipeline
from careercrew_core.state.settings import load_settings


def main() -> None:
    settings = load_settings()
    files: list[Path] = []
    if len(sys.argv) > 1:
        for raw in sys.argv[1:]:
            p = Path(raw)
            files.extend(p.glob("**/*") if p.is_dir() else [p])
    else:
        files = sorted(
            p for p in (PROJECT_ROOT / "data" / "uploads").glob("*")
            if p.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".docx"}
        )
    files = sorted({f.resolve() for f in files if f.is_file()})
    if not files:
        print("无文档可摄取")
        return

    print(
        f"LLM: {settings.llm.model} | Embedding: {settings.embedding.provider} | "
        f"Store: {settings.vector_store.backend} | VLM: {settings.vlm.model}"
    )
    print(f"待摄取 {len(files)} 个文档...")

    embedding = create_embedding(settings)
    store = create_vector_store(settings)
    contextualizer = None
    if settings.rag.chunking.contextual:
        llm = create_llm(settings, max_tokens=256)
        contextualizer = Contextualizer(llm)

    pipe = MultimodalIngestionPipeline(
        embedding, store, contextualizer=contextualizer,
        contextual=settings.rag.chunking.contextual,
        output_dir=settings.rag.loaders.output_dir,
        loader_provider=settings.rag.loaders.provider,
        loader_api_key=settings.rag.loaders.api_key,
        loader_device=settings.rag.loaders.device,
        loader_method=settings.rag.loaders.method,
        loader_formula=settings.rag.loaders.formula,
        loader_table=settings.rag.loaders.table,
        loader_language=settings.rag.loaders.language,
        loader_model_version=settings.rag.loaders.model_version,
        loader_poll_interval=settings.rag.loaders.poll_interval,
        loader_timeout=settings.rag.loaders.timeout,
        chunk_size=settings.rag.chunking.chunk_size,
        chunk_overlap=settings.rag.chunking.chunk_overlap,
    )

    total = 0
    for f in files:
        try:
            n = pipe.ingest_file(f)
            print(f"  {f}: {n} points")
            total += n
        except ParsingError as e:
            print(f"  {f}: doc_type=error 跳过（{e}）")
        except Exception as e:
            print(f"  {f}: 失败（{type(e).__name__}: {e}）")
    print(
        f"摄取完成：{len(files)} 文档，{total} points -> Qdrant collection "
        f"{settings.vector_store.collections['knowledge']}"
    )


if __name__ == "__main__":
    main()
