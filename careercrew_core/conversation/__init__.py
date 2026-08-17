"""careercrew_core.conversation - 对话核心存储（Phase 1）。

conversations / conversation_turns / messages / agent_runs /
agent_run_retrievals / agent_run_tool_calls 表 + ConversationStore 领域服务 + UUIDv7。

存储：Postgres（生产）| FakeConversationDb（测试），统一 ConversationDb 契约。
"""
from careercrew_core.conversation.db import (
    ConversationDb,
    FakeConversationDb,
    PostgresConversationDb,
    create_conversation_db,
)
from careercrew_core.conversation.store import ConversationStore, OwnershipError
from careercrew_core.conversation.uuid7 import uuid7

__all__ = [
    "ConversationDb",
    "PostgresConversationDb",
    "FakeConversationDb",
    "create_conversation_db",
    "ConversationStore",
    "OwnershipError",
    "uuid7",
]
