"""careercrew_core.rag.loaders - 文档加载（文本直读 + MinerU 多模态解析）。"""
from careercrew_core.rag.loaders.base_loader import (
    BaseLoader,
    Document,
    ParsedDocument,
    ParsedObject,
    ParsedPage,
)
from careercrew_core.rag.loaders.loader_factory import create_loader
from careercrew_core.rag.loaders.markdown_loader import MarkdownLoader
from careercrew_core.rag.loaders.mineru_loader import MinerULoader, ParsingError

__all__ = [
    "BaseLoader",
    "Document",
    "ParsedDocument",
    "ParsedPage",
    "ParsedObject",
    "create_loader",
    "MarkdownLoader",
    "MinerULoader",
    "ParsingError",
]
