"""知识库 Ingestion Pipeline（D4）：load -> split -> contextualize -> embed -> upsert。

Contextual Chunking 的上下文前缀只用于 embedding（提升检索），存原始块文本（agent 看干净文本）。
doc_id 取自 source 文件名 stem，chunk id = f"{doc_id}_{i:04d}"（跨文件唯一）。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from careercrew_ai.embedding.base_embedding import BaseEmbedding
from careercrew_ai.vector_store.base_vector_store import BaseVectorStore, VectorRecord
from careercrew_core.rag.chunking.document_chunker import DocumentChunker

if TYPE_CHECKING:
    from careercrew_core.rag.chunking.contextualizer import Contextualizer


class IngestionPipeline:
    def __init__(
        self,
        embedding: BaseEmbedding,
        store: BaseVectorStore,
        contextualizer: Contextualizer | None = None,
        contextual: bool = True,
        chunk_size: int = 800,
        chunk_overlap: int = 100,
        colbert_store: bool = False,
    ) -> None:
        self._embedding = embedding
        self._store = store
        self._contextualizer = contextualizer
        self._contextual = contextual and contextualizer is not None
        self._colbert_store = colbert_store
        self._chunker = DocumentChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    def ingest_text(self, text: str, source: str = "", metadata: dict | None = None) -> int:
        """摄取一段文本：切分 -> contextualize -> embed -> upsert。返回 chunk 数。"""
        chunks = self._chunker.chunk(text, source=source, metadata=metadata)
        doc_id = Path(source).stem if source else "doc"

        # contextualize（上下文前缀只用于 embedding）
        texts_to_embed: list[str] = []
        for c in chunks:
            if self._contextual and self._contextualizer:
                c = self._contextualizer.contextualize(c, text)
            texts_to_embed.append(c.contextualized_text or c.text)

        # 批量 encode
        emb_out = self._embedding.encode(texts_to_embed)

        # M7 可选：colbert token 矩阵随 payload 落库（库体积显著增大，开关默认关）
        def _colbert_meta(i: int) -> dict:
            if not (self._colbert_store and emb_out.colbert):
                return {}
            try:
                import numpy as np

                return {"colbert": [[float(x) for x in row]
                                    for row in np.asarray(emb_out.colbert[i])]}
            except Exception:
                return {}

        # upsert（存原始块文本）
        records = [
            VectorRecord(
                id=f"{doc_id}_{i:04d}",
                dense=emb_out.dense[i],
                sparse=emb_out.sparse[i] if emb_out.sparse else None,
                text=c.text,
                metadata={**c.metadata, "doc": doc_id, **_colbert_meta(i)},
            )
            for i, c in enumerate(chunks)
        ]
        self._store.upsert(records)
        return len(records)

    def ingest_file(self, path: str | Path, metadata: dict | None = None) -> int:
        p = Path(path)
        # 统一加载：Markdown 直读；其余格式走 MinerU 多模态管线（pipeline_multimodal）
        from careercrew_core.rag.loaders.loader_factory import create_loader

        doc = create_loader(str(p)).load(str(p))
        meta = {"source": str(p), **(doc.metadata or {}), **(metadata or {})}
        return self.ingest_text(doc.text, source=str(p), metadata=meta)
