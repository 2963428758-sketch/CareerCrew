"""MarkItDown loader（§3.7.4）：PDF/Word/Excel/PPT/HTML 统一转 Markdown。"""
from __future__ import annotations

from pathlib import Path

from careercrew_core.rag.loaders.base_loader import BaseLoader, Document


class MarkItDownLoader(BaseLoader):
    def __init__(self) -> None:
        from markitdown import MarkItDown

        self._converter = MarkItDown()

    def load(self, path: str) -> Document:
        p = Path(path)
        result = self._converter.convert(str(p))
        return Document(
            id=str(p),
            text=result.text_content or "",
            metadata={"source_path": str(p), "doc_type": p.suffix.lstrip(".") or "unknown"},
        )
