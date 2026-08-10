"""loader 工厂：文本直读（多模态 RAG 起，非文本走 MinerU 多模态管线）。"""
from __future__ import annotations

from pathlib import Path

from careercrew_core.rag.loaders.base_loader import BaseLoader
from careercrew_core.rag.loaders.markdown_loader import MarkdownLoader

_MARKDOWN_EXTS = {".md", ".markdown", ".txt"}


def create_loader(path: str) -> BaseLoader:
    ext = Path(path).suffix.lower()
    if ext in _MARKDOWN_EXTS:
        return MarkdownLoader()
    raise ValueError(
        f"非文本格式 {ext or 'unknown'} 请走 MinerU 多模态管线（MultimodalIngestionPipeline）"
    )
