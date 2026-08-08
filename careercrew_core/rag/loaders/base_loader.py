"""文档加载抽象（§3.7.4）。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Document:
    """统一文档契约：text(markdown) + metadata。"""

    id: str
    text: str
    metadata: dict = field(default_factory=dict)


class BaseLoader(ABC):
    """load(path) -> Document（text + metadata）。"""

    @abstractmethod
    def load(self, path: str) -> Document: ...
