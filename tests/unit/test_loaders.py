"""多格式 loader 测试（§3.7.4）。"""
from __future__ import annotations

from careercrew_core.rag.loaders.loader_factory import create_loader
from careercrew_core.rag.loaders.markdown_loader import MarkdownLoader
from careercrew_core.rag.loaders.markitdown_loader import MarkItDownLoader


def test_markdown_loader(tmp_path) -> None:
    f = tmp_path / "a.md"
    f.write_text("# 标题\n\n内容", encoding="utf-8")
    doc = MarkdownLoader().load(str(f))
    assert "# 标题" in doc.text
    assert doc.metadata["doc_type"] == "markdown"


def test_loader_factory_routing() -> None:
    assert isinstance(create_loader("x.md"), MarkdownLoader)
    assert isinstance(create_loader("x.txt"), MarkdownLoader)
    assert isinstance(create_loader("x.pdf"), MarkItDownLoader)
    assert isinstance(create_loader("x.docx"), MarkItDownLoader)
