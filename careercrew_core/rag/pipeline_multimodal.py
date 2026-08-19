"""多模态入库管线（MULTIMODAL_RAG_SPEC 解析与入库）。

文件路由：
- md/txt -> Markdown 直读 + 切分 + Contextual Chunking + BGE-M3（原文本路径，R6）
- PDF/图片/docx/... -> MinerU 子进程解析 -> 页面单元 + 对象单元
  - 图片内容由 MinerU 抽取为文本（OCR/Markdown），统一走 BGE-M3 dense/sparse
  - 页面图/对象图路径保留在 payload（VLM 看图回答时展示），不参与向量化

点 id 幂等：页面 ``{doc_id}_p{page:03d}``、对象 ``{doc_id}_o{page:03d}_{idx:02d}``，
重灌同 id 覆盖（Qdrant upsert）。
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from careercrew_ai.embedding.base_embedding import BaseEmbedding
from careercrew_ai.vector_store.base_vector_store import BaseVectorStore, VectorRecord
from careercrew_core.rag.chunking.document_chunker import DocumentChunker
from careercrew_core.rag.loaders.base_loader import ParsedDocument
from careercrew_core.rag.loaders.markdown_loader import MarkdownLoader
from careercrew_core.rag.loaders.mineru_api_loader import MinerUApiLoader
from careercrew_core.rag.loaders.mineru_loader import MinerULoader
from careercrew_core.tracing.langsmith import traced_call

if TYPE_CHECKING:
    from careercrew_core.rag.chunking.contextualizer import Contextualizer

_TEXT_EXTS = {".md", ".markdown", ".txt"}


class MultimodalIngestionPipeline:
    def __init__(
        self,
        embedding: BaseEmbedding,
        store: BaseVectorStore,
        contextualizer: "Contextualizer | None" = None,
        contextual: bool = True,
        object_extraction: bool = True,
        output_dir: str | Path = "./data/parsed",
        loader_provider: str = "api",
        loader_api_key: str = "",
        loader_device: str = "cpu",
        loader_method: str = "auto",
        loader_formula: bool = True,
        loader_table: bool = True,
        loader_language: str = "ch",
        loader_model_version: str = "vlm",
        loader_poll_interval: int = 5,
        loader_timeout: int = 1800,
        chunk_size: int = 800,
        chunk_overlap: int = 100,
    ) -> None:
        self._embedding = embedding
        self._store = store
        self._contextualizer = contextualizer
        self._contextual = contextual and contextualizer is not None
        self._object_extraction = object_extraction
        self._output_dir = Path(output_dir)
        self._loader_provider = loader_provider
        self._loader_api_key = loader_api_key
        self._loader_device = loader_device
        self._loader_method = loader_method
        self._loader_formula = loader_formula
        self._loader_table = loader_table
        self._loader_language = loader_language
        self._loader_model_version = loader_model_version
        self._loader_poll_interval = loader_poll_interval
        self._loader_timeout = loader_timeout
        self._chunker = DocumentChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    def _make_loader(self, output_dir: str | Path | None = None):
        """按 provider 路由：api（云端，默认）| local（本地子进程）。

        output_dir：按用户/文档隔离的解析产物目录（None 用管线默认目录）。
        """
        out_dir = self._output_dir if output_dir is None else Path(output_dir)
        if self._loader_provider == "local":
            return MinerULoader(
                out_dir,
                device=self._loader_device,
                method=self._loader_method,
                formula=self._loader_formula,
            )
        return MinerUApiLoader(
            out_dir,
            api_key=self._loader_api_key,
            model_version=self._loader_model_version,
            formula=self._loader_formula,
            table=self._loader_table,
            language=self._loader_language,
            poll_interval=self._loader_poll_interval,
            timeout=self._loader_timeout,
        )

    def ingest_text(
        self,
        text: str,
        source: str = "",
        metadata: dict | None = None,
        progress_cb: Callable[[str, float], None] | None = None,
        category: str = "",
    ) -> int:
        """纯文本入库（根 run careercrew.ingest，Contextualizer 逐 chunk LLM 不刷配额）。"""
        return traced_call(
            self._ingest_text_impl,
            name="careercrew.ingest",
            run_type="chain",
            run_metadata={"endpoint": "ingest"},
            text=text, source=source, metadata=metadata, progress_cb=progress_cb, category=category,
        )

    def _ingest_text_impl(
        self,
        text: str,
        source: str = "",
        metadata: dict | None = None,
        progress_cb: Callable[[str, float], None] | None = None,
        category: str = "",
    ) -> int:
        """纯文本路径：切分 -> contextualize -> BGE-M3 -> upsert（无视觉向量）。"""
        chunks = self._chunker.chunk(text, source=source, metadata=metadata)
        doc_id = Path(source).stem if source else "doc"
        texts_to_embed: list[str] = []
        for c in chunks:
            if self._contextual and self._contextualizer:
                c = self._contextualizer.contextualize(c, text)
            texts_to_embed.append(c.contextualized_text or c.text)
        if progress_cb:
            progress_cb("vectorize", 0.6)
        emb = self._embedding.encode(texts_to_embed)
        records = [
            VectorRecord(
                id=f"{doc_id}_{i:04d}",
                dense=emb.dense[i],
                sparse=emb.sparse[i] if emb.sparse else None,
                text=c.text,
                metadata={**c.metadata, "doc": doc_id, "category": category},
            )
            for i, c in enumerate(chunks)
        ]
        if records:
            if progress_cb:
                progress_cb("store", 0.95)
            self._store.upsert(records)
        return len(records)

    def ingest_file(
        self,
        path: str | Path,
        metadata: dict | None = None,
        progress_cb: Callable[[str, float], None] | None = None,
        category: str = "",
        output_dir: str | Path | None = None,
    ) -> int:
        """文件入库（根 run careercrew.ingest）；output_dir 按用户/文档隔离解析产物。"""
        return traced_call(
            self._ingest_file_impl,
            name="careercrew.ingest",
            run_type="chain",
            run_metadata={"endpoint": "ingest"},
            path=path, metadata=metadata, progress_cb=progress_cb, category=category,
            output_dir=output_dir,
        )

    def _ingest_file_impl(
        self,
        path: str | Path,
        metadata: dict | None = None,
        progress_cb: Callable[[str, float], None] | None = None,
        category: str = "",
        output_dir: str | Path | None = None,
    ) -> int:
        """文件入库：md/txt 走文本路径；其余走 MinerU 多模态路径。"""
        p = Path(path)
        if p.suffix.lower() in _TEXT_EXTS:
            doc = MarkdownLoader().load(str(p))
            meta = {**doc.metadata, **(metadata or {})}
            return self.ingest_text(
                doc.text, source=str(p), metadata=meta, progress_cb=progress_cb, category=category,
            )
        parsed = self.parse_file(p, output_dir, progress_cb=progress_cb)
        if progress_cb:
            progress_cb("vectorize", 0.6)
        return self._ingest_parsed(parsed, metadata, progress_cb=progress_cb, category=category)

    def parse_file(
        self,
        path: str | Path,
        output_dir: str | Path | None = None,
        progress_cb: Callable[[str, float], None] | None = None,
    ) -> ParsedDocument:
        """仅解析不向量化：返回 ParsedDocument（页面/对象单元），供附件/临时文件取文本。

        与 ingest_file 共用同一 loader 路由（api/local），产出目录按调用方隔离。
        """
        if progress_cb:
            progress_cb("parse", 0.05)
        return self._make_loader(output_dir).parse(Path(path))

    def _ingest_parsed(
        self,
        parsed: ParsedDocument,
        metadata: dict | None = None,
        progress_cb: Callable[[str, float], None] | None = None,
        category: str = "",
    ) -> int:
        meta = metadata or {}
        base_meta = {
            **meta,
            "doc": parsed.doc_id,
            "source": meta.get("source", "") or parsed.metadata.get("source_path", ""),
            "category": category,
        }
        doc_text = "\n\n".join(pg.markdown for pg in parsed.pages)
        records: list[VectorRecord] = []

        # 页面单元
        non_empty_pages = [
            pg for pg in sorted(parsed.pages, key=lambda x: x.page_no)
            if pg.markdown.strip()
        ]
        if non_empty_pages:
            texts = []
            for pg in non_empty_pages:
                text_to_embed = pg.markdown
                if self._contextual and self._contextualizer:
                    ctx = self._contextualizer.contextualize(
                        _SimpleChunk(pg.markdown), doc_text
                    )
                    text_to_embed = ctx.contextualized_text or pg.markdown
                texts.append(text_to_embed)
            emb = self._embedding.encode(texts)
            for i, pg in enumerate(non_empty_pages):
                records.append(
                    VectorRecord(
                        id=f"{parsed.doc_id}_p{pg.page_no:03d}",
                        dense=emb.dense[i],
                        sparse=emb.sparse[i] if emb.sparse else None,
                        text=pg.markdown,
                        metadata={
                            **base_meta,
                            "doc": parsed.doc_id,
                            "page": pg.page_no,
                            "type": "page",
                            "image_path": pg.image_path,
                        },
                    )
                )

        # 对象单元（仅保留有文本的：图/表裁剪图 + 文本；无文本裁剪图由页面文本覆盖）
        if self._object_extraction:
            text_objs = [obj for obj in parsed.objects if (obj.text or "").strip()]
            obj_emb = None
            if text_objs:
                obj_emb = self._embedding.encode([obj.text.strip() for obj in text_objs])
            text_iter = 0
            for idx, obj in enumerate(parsed.objects):
                text = obj.text.strip()
                if not text:
                    continue
                dense = obj_emb.dense[text_iter]
                sparse = obj_emb.sparse[text_iter] if obj_emb.sparse else None
                text_iter += 1
                records.append(
                    VectorRecord(
                        id=f"{parsed.doc_id}_o{obj.page_no:03d}_{idx:02d}",
                        dense=dense,
                        sparse=sparse,
                        text=text,
                        metadata={
                            **base_meta,
                            "doc": parsed.doc_id,
                            "page": obj.page_no,
                            "type": "object",
                            "image_path": obj.image_path,
                            "bbox": str(obj.bbox) if obj.bbox else "",
                        },
                    )
                )

        records = [r for r in records if len(r.dense) > 0]
        if records:
            if progress_cb:
                progress_cb("store", 0.95)
            self._store.upsert(records)
        return len(records)


class _SimpleChunk:
    """Contextualizer 契约适配（仅需要 .text / .contextualized_text）。"""

    def __init__(self, text: str) -> None:
        self.text = text
        self.contextualized_text = ""
