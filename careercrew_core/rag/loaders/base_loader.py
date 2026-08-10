"""文档加载抽象（§3.7.4 + 多模态 RAG）。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Document:
    """统一文档契约：text(markdown) + metadata。"""

    id: str
    text: str
    metadata: dict = field(default_factory=dict)


@dataclass
class ParsedPage:
    """多模态解析：单页渲染图 + 该页 Markdown 文本。"""

    page_no: int
    image_path: str
    markdown: str


@dataclass
class ParsedObject:
    """多模态解析：对象块（图/表裁剪图 + 文本）。"""

    page_no: int
    image_path: str
    text: str = ""
    bbox: list[int] | None = None


@dataclass
class ParsedDocument:
    """MinerU 解析产物：页面 + 对象块。"""

    doc_id: str
    pages: list[ParsedPage] = field(default_factory=list)
    objects: list[ParsedObject] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_text(self) -> str:
        """拼接全部页面 Markdown（resume 上传 / 纯文本消费用）。"""
        return "\n\n".join(p.markdown for p in sorted(self.pages, key=lambda x: x.page_no))


class BaseLoader(ABC):
    """load(path) -> Document（text + metadata）。"""

    @abstractmethod
    def load(self, path: str) -> Document: ...
