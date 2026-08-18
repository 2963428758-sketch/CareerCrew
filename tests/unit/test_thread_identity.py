from __future__ import annotations

from careercrew_api.runtime import CareerCrewRuntime
from careercrew_core.conversation.db import FakeConversationDb
from careercrew_core.conversation.store import ConversationStore
from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.threads import ThreadStore


def make_runtime() -> CareerCrewRuntime:
    runtime = CareerCrewRuntime()
    runtime._initialized = True
    runtime.memory_db = FakeMemoryDb()
    runtime.thread_store = ThreadStore(runtime.memory_db)
    runtime.conversation_store = ConversationStore(FakeConversationDb())
    return runtime


def test_memory_thread_identity_is_normalized_from_conversation_uuid():
    runtime = make_runtime()
    conversation = runtime.conversation_store.ensure_conversation(
        "legacy-1", "u-1", "chat", title="首个问题"
    )

    runtime._ensure_thread("legacy-1", "u-1", module="chat", title="首个问题")
    runtime._ensure_thread(
        conversation["id"], "u-1", module="chat", title="第二个问题"
    )

    rows = runtime.thread_store.list("u-1", module="chat")
    assert [row["thread_id"] for row in rows] == ["legacy-1"]
    assert rows[0]["title"] == "首个问题"


def test_get_threads_hides_preexisting_uuid_alias_row():
    runtime = make_runtime()
    conversation = runtime.conversation_store.ensure_conversation(
        "legacy-1", "u-1", "chat", title="首个问题"
    )
    runtime.thread_store.upsert(
        "u-1", "legacy-1", title="首个问题", module="chat"
    )
    # 模拟修复上线前已经写入的第二条 UUID memory 行。
    runtime.thread_store.upsert(
        "u-1", conversation["id"], title="第二个问题", module="chat"
    )

    rows = runtime.get_threads("u-1", module="chat")

    assert len(rows) == 1
    assert rows[0]["thread_id"] == "legacy-1"
