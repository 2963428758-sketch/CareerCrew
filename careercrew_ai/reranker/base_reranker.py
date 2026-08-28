"""Reranker 抽象基类 + 工厂（A4 骨架）。

分层：careercrew_ai 最底层，不反向依赖 careercrew_core（Settings 仅 TYPE_CHECKING）。

D3 将注册 siliconflow -> SiliconFlowReranker / local_bge -> 本地 bge-reranker。
A4 提供 NoneReranker（真实 passthrough，D3 回退用）与 FakeReranker（路由验证）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from careercrew_ai.vector_store.base_vector_store import QueryResult

if TYPE_CHECKING:
    from careercrew_core.state.settings import Settings


class BaseReranker(ABC):
    """Reranker 抽象契约。"""

    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: list[QueryResult],
        top_k: int | None = None,
    ) -> list[QueryResult]: ...


class NoneReranker(BaseReranker):
    """不重排：原序返回（截断到 top_k）。

    D3 rerank.backend=none 时用；rerank API 失败时回退（对齐 DEV_SPEC 5.7）。
    """

    def __init__(self, settings: Settings | None = None) -> None:
        pass

    def rerank(self, query, candidates, top_k=None):
        return candidates[:top_k] if top_k is not None else list(candidates)


class FakeReranker(BaseReranker):
    """确定性 Fake：按 id 字典序重排（验证路由用）。"""

    def __init__(self, settings: Settings | None = None) -> None:
        pass

    def rerank(self, query, candidates, top_k=None):
        ranked = sorted(candidates, key=lambda c: c.id)
        return ranked[:top_k] if top_k is not None else ranked


_RERANKER_REGISTRY: dict[str, type[BaseReranker]] = {
    "none": NoneReranker,
    "fake": FakeReranker,
}


def create_reranker(settings: Settings) -> BaseReranker:
    """按 settings.rerank.backend 路由到具体实现。"""
    backend = settings.rerank.backend
    if backend == "none":
        return NoneReranker(settings)
    if backend == "fake":
        return FakeReranker(settings)
    if backend == "siliconflow":
        from careercrew_ai.reranker.siliconflow_reranker import SiliconFlowReranker

        return SiliconFlowReranker(settings)
    if backend == "dashscope":
        from careercrew_ai.reranker.dashscope_reranker import DashScopeReranker

        return DashScopeReranker(settings)
    if backend == "siliconflow_vl":
        from careercrew_ai.reranker.siliconflow_vl_reranker import SiliconFlowVLReranker

        return SiliconFlowVLReranker(settings)
    raise NotImplementedError(
        f"rerank backend '{backend}' 尚未实现（已实现: none, fake, siliconflow, dashscope, siliconflow_vl）"
    )


def register_reranker(backend: str, cls: type[BaseReranker]) -> None:
    _RERANKER_REGISTRY[backend] = cls
