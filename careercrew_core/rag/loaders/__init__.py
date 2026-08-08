"""careercrew_core.rag.loaders - 多格式文档加载（§3.7.4）。"""
from careercrew_core.rag.loaders.base_loader import BaseLoader, Document
from careercrew_core.rag.loaders.loader_factory import create_loader
from careercrew_core.rag.loaders.markdown_loader import MarkdownLoader
from careercrew_core.rag.loaders.markitdown_loader import MarkItDownLoader

__all__ = ["BaseLoader", "Document", "create_loader", "MarkdownLoader", "MarkItDownLoader"]
