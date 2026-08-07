"""BGE-M3 三合一 Embedding（D1）：dense + sparse + colbert 一次前向。

本地 FlagEmbedding 跑（API 只给 dense，三合一只有本地能拿；ADR-3）。
稀疏路免额外 BM25 倒排索引，与 Milvus 原生 hybrid 直接对接。

FlagEmbedding 在 __init__ 内 lazy import，避免 import 本模块就加载 2GB 模型。
sparse 的 token id 从 str 转 int（Milvus SPARSE_FLOAT_VECTOR 要 int key）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from careercrew_ai.embedding.base_embedding import BaseEmbedding, EmbeddingOutput

if TYPE_CHECKING:
    from careercrew_core.state.settings import Settings


class BGEM3Embedding(BaseEmbedding):
    def __init__(self, settings: Settings) -> None:
        from FlagEmbedding import BGEM3FlagModel

        cfg = settings.embedding
        self._model = BGEM3FlagModel(cfg.model_path, use_fp16=cfg.use_fp16)
        self._batch_size = cfg.batch_size

    def encode(self, texts: list[str]) -> EmbeddingOutput:
        out = self._model.encode(
            texts,
            batch_size=self._batch_size,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=True,
        )
        # lexical_weights: list[dict{str_token_id: float}] -> 转 int key（Milvus 用）
        sparse = [
            {int(k): float(v) for k, v in weights.items()}
            for weights in out["lexical_weights"]
        ]
        return EmbeddingOutput(
            dense=out["dense_vecs"],       # (n, 1024) float32
            sparse=sparse,                 # list[dict[int, float]]
            colbert=out["colbert_vecs"],   # list[(n_tokens, 1024)]
        )
