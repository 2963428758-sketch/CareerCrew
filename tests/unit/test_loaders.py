"""loader 测试（文本直读 + 工厂路由；MinerU 见 test_mineru_loader）。"""
from __future__ import annotations

import pytest

from careercrew_core.rag.loaders.loader_factory import create_loader
from careercrew_core.rag.loaders.markdown_loader import MarkdownLoader


def test_markdown_loader(tmp_path) -> None:
    f = tmp_path / "a.md"
    f.write_text("# 标题\n\n内容", encoding="utf-8")
    doc = MarkdownLoader().load(str(f))
    assert "# 标题" in doc.text
    assert doc.metadata["doc_type"] == "markdown"


def test_loader_factory_routing() -> None:
    assert isinstance(create_loader("x.md"), MarkdownLoader)
    assert isinstance(create_loader("x.txt"), MarkdownLoader)
    with pytest.raises(ValueError):
        create_loader("x.pdf")
