"""careercrew_ai.embedding - Embedding 抽象与工厂。"""
from careercrew_ai.embedding.base_embedding import (
    BaseEmbedding,
    EmbeddingOutput,
    FakeEmbedding,
    create_embedding,
    register_embedding,
)

__all__ = [
    "BaseEmbedding",
    "EmbeddingOutput",
    "FakeEmbedding",
    "create_embedding",
    "register_embedding",
]
