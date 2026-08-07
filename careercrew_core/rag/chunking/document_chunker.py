"""文档切分（D1）：Document -> Chunks（调 ai.splitter）。"""
from __future__ import annotations

from dataclasses import dataclass, field

from careercrew_ai.splitter.recursive_splitter import RecursiveSplitter


@dataclass
class Chunk:
    """检索块（ingestion 最小单元）。"""

    id: str
    text: str
    metadata: dict = field(default_factory=dict)
    contextualized_text: str = ""  # contextualizer 填充（带文档级上下文前置）


class DocumentChunker:
    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 100) -> None:
        self._splitter = RecursiveSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    def chunk(self, text: str, source: str = "", metadata: dict | None = None) -> list[Chunk]:
        meta = dict(metadata or {})
        if source:
            meta.setdefault("source", source)
        texts = self._splitter.split(text)
        return [
            Chunk(id=f"c_{i:04d}", text=t, metadata=dict(meta))
            for i, t in enumerate(texts)
        ]
