"""careercrew_core.memory - 统一记忆子系统。

存储：Postgres（生产）| FakeMemoryDb（测试），统一 MemoryDb 契约。
分层：短期（checkpointer 管对话历史）/ 情景（episodic_events 树）/
语义（semantic_facts 事实）+ 治理（policy）+ 检索（LLM 路由 + 向量）+
生命周期（compaction / consolidation / redaction）。
"""
from careercrew_core.memory.compaction import Compactor
from careercrew_core.memory.consolidation import Consolidator
from careercrew_core.memory.db import FakeMemoryDb, MemoryDb, PostgresMemoryDb, create_memory_db
from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.injection import MemoryInjector
from careercrew_core.memory.policy import MemoryPolicyStore
from careercrew_core.memory.redaction import redact_content, redact_secrets
from careercrew_core.memory.router import MemoryRouter
from careercrew_core.memory.semantic import SemanticFactStore
from careercrew_core.memory.short_term import ShortTermMemory, estimate_tokens
from careercrew_core.memory.threads import ThreadStore
from careercrew_core.memory.types import (
    MemoryEntry,
    MemoryPolicy,
    SemanticFact,
    TreeNode,
    UserPreferences,
    UserProfile,
    UserModel,
)
from careercrew_core.memory.vector_index import VectorIndex

__all__ = [
    "MemoryDb",
    "PostgresMemoryDb",
    "FakeMemoryDb",
    "create_memory_db",
    "EpisodicMemory",
    "ShortTermMemory",
    "estimate_tokens",
    "MemoryEntry",
    "SemanticFact",
    "MemoryPolicy",
    "TreeNode",
    "UserProfile",
    "UserPreferences",
    "UserModel",
    "SemanticFactStore",
    "MemoryPolicyStore",
    "ThreadStore",
    "MemoryRouter",
    "MemoryInjector",
    "Consolidator",
    "redact_content",
    "redact_secrets",
    "VectorIndex",
    "Compactor",
]
