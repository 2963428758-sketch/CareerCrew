from __future__ import annotations

from types import SimpleNamespace

from careercrew_api.runtime import CareerCrewRuntime


def test_runtime_builds_workspace_semantic_search_without_full_ai_stack() -> None:
    runtime = CareerCrewRuntime()
    runtime._stores_ready = True
    runtime.settings = SimpleNamespace(
        embedding=SimpleNamespace(provider="fake"),
        vector_store=SimpleNamespace(
            backend="fake",
            collections={"conversation_messages": "workspace-message-test"},
        ),
    )

    def fail_full_ai_initialization():
        raise AssertionError("workspace search must not initialize the full AI stack")

    runtime._init_heavy_locked = fail_full_ai_initialization

    index = runtime._ensure_workspace_semantic_search(
        message_loader=lambda _owner_id: [],
    )

    assert index is not None
    assert runtime._initialized is False
    assert runtime.embedding is not None
    assert runtime.store is None


def test_runtime_reuses_workspace_semantic_search_instance() -> None:
    runtime = CareerCrewRuntime()
    runtime._stores_ready = True
    runtime.settings = SimpleNamespace(
        embedding=SimpleNamespace(provider="fake"),
        vector_store=SimpleNamespace(
            backend="fake",
            collections={"conversation_messages": "workspace-message-test"},
        ),
    )
    def loader(_owner_id):
        return []

    first = runtime._ensure_workspace_semantic_search(message_loader=loader)
    second = runtime._ensure_workspace_semantic_search(message_loader=loader)

    assert first is second


def test_workspace_search_route_attaches_the_lazy_backend() -> None:
    from careercrew_api.routers.workspace import search_workspace
    from careercrew_core.conversation.db import FakeConversationDb
    from careercrew_core.conversation.store import ConversationStore

    store = ConversationStore(FakeConversationDb())
    store.ensure_conversation("thread-1", "alice", "chat", title="Semantic")
    turn = store.next_turn("thread-1", "alice")
    message = store.add_user_message(
        turn["id"], "thread-1", "alice", "RAG interview", "completed"
    )

    class _Backend:
        def search(self, query, owner_id, limit):
            return {
                "mode": "embedding",
                "query": query,
                "items": [{"message_id": message["id"]}],
                "total": 1,
            }

    class _Runtime:
        conversation_store = store

        def _ensure_stores(self):
            return None

        def _ensure_workspace_semantic_search(self, *, message_loader):
            assert callable(message_loader)
            return _Backend()

    result = search_workspace(
        user={"id": "alice"}, q="RAG", limit=7, rt=_Runtime()
    )

    assert result["mode"] == "embedding"
    assert result["items"][0]["message_id"] == message["id"]
