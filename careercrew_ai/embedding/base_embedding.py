"""Embedding 抽象基类 + 工厂（A4 骨架）。

分层：careercrew_ai 是最底层，不反向依赖 careercrew_core。Settings 仅作类型提示
（TYPE_CHECKING），运行时鸭子类型读取 settings.embedding.*。

D1 将注册 bge_m3_local -> BGEM3Embedding（本地 BGE-M3 三合一）。
A4 仅提供 FakeEmbedding 验证工厂路由与契约。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from careercrew_core.state.settings import Settings


@dataclass
class EmbeddingOutput:
    """BGE-M3 风格 embedding 输出：dense 必有，sparse/colbert 视实现。"""

    dense: np.ndarray  # shape (n_texts, dim)
    sparse: list[dict[int, float]] | None = None  # 每条文本 {token_id: weight}
    colbert: np.ndarray | None = None  # shape (n_texts, n_tokens, dim)


class BaseEmbedding(ABC):
    """Embedding 抽象契约。"""

    @abstractmethod
    def encode(self, texts: list[str]) -> EmbeddingOutput:
        """编码文本 -> EmbeddingOutput（dense 必有，sparse/colbert 视实现）。"""


class FakeEmbedding(BaseEmbedding):
    """确定性 Fake 实现（A4 路由验证 / 单测占位）。"""

    def __init__(self, settings: Settings) -> None:
        self._dim = 8

    def encode(self, texts: list[str]) -> EmbeddingOutput:
        n = len(texts)
        dense = np.zeros((n, self._dim), dtype=np.float32)
        for i, t in enumerate(texts):
            dense[i, len(t) % self._dim] = 1.0
        return EmbeddingOutput(dense=dense)


# 工厂注册表：provider -> 实现类。D1 注册 bge_m3_local。
_EMBEDDING_REGISTRY: dict[str, type[BaseEmbedding]] = {"fake": FakeEmbedding}


def create_embedding(settings: Settings) -> BaseEmbedding:
    """按 settings.embedding.provider 路由到具体实现。"""
    provider = settings.embedding.provider
    cls = _EMBEDDING_REGISTRY.get(provider)
    if cls is None:
        raise NotImplementedError(
            f"embedding provider '{provider}' 尚未实现（D1 将实现 bge_m3_local）"
        )
    return cls(settings)


def register_embedding(provider: str, cls: type[BaseEmbedding]) -> None:
    """注册新 provider（D1 注册 bge_m3_local 时调用）。"""
    _EMBEDDING_REGISTRY[provider] = cls
