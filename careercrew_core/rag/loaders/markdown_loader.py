"""Markdown / 纯文本直读 loader（§3.7.4）。"""
from __future__ import annotations

from pathlib import Path

from careercrew_core.rag.loaders.base_loader import BaseLoader, Document


class MarkdownLoader(BaseLoader):
    def load(self, path: str) -> Document:
        p = Path(path)
        return Document(
            id=str(p),
            text=p.read_text(encoding="utf-8"),
            metadata={"source_path": str(p), "doc_type": "markdown"},
        )
