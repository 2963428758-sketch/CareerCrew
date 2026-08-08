"""loader 工厂：按扩展名路由（§3.7.4）。"""
from __future__ import annotations

from pathlib import Path

from careercrew_core.rag.loaders.base_loader import BaseLoader
from careercrew_core.rag.loaders.markdown_loader import MarkdownLoader
from careercrew_core.rag.loaders.markitdown_loader import MarkItDownLoader

_MARKDOWN_EXTS = {".md", ".markdown", ".txt"}


def create_loader(path: str) -> BaseLoader:
    ext = Path(path).suffix.lower()
    if ext in _MARKDOWN_EXTS:
        return MarkdownLoader()
    return MarkItDownLoader()
