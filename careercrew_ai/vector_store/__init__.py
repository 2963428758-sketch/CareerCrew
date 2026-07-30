"""careercrew_ai.vector_store - 向量库抽象与工厂。"""
from careercrew_ai.vector_store.base_vector_store import (
    BaseVectorStore,
    FakeVectorStore,
    QueryResult,
    VectorRecord,
    create_vector_store,
    register_vector_store,
)

__all__ = [
    "BaseVectorStore",
    "VectorRecord",
    "QueryResult",
    "FakeVectorStore",
    "create_vector_store",
    "register_vector_store",
]
