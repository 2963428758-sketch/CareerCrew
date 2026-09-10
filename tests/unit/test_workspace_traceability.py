from __future__ import annotations

from careercrew_core.conversation.db import FakeConversationDb
from careercrew_core.conversation.store import ConversationStore
from careercrew_core.workspace.traceability import WorkspaceTraceability


def _seed(store: ConversationStore, user_id: str = "alice", thread_id: str = "t-a") -> dict:
    store.ensure_conversation(thread_id, user_id, "chat", title="准备面试")
    turn = store.next_turn(thread_id, user_id)
    question = store.add_user_message(
        turn["id"], thread_id, user_id, "请帮我准备 RAG 面试", "completed"
    )
    answer = store.add_assistant_message(
        turn["id"], thread_id, user_id, "准备召回、重排和评测案例", None, None
    )
    store.set_message_content(user_id, answer["id"], answer["content"], metadata={"sources": ["kb-1"]})
    return {"thread": thread_id, "question": question, "answer": answer}


def test_search_bookmark_branch_and_action_item_are_owner_scoped() -> None:
    store = ConversationStore(FakeConversationDb())
    seeded = _seed(store)
    service = WorkspaceTraceability(store)

    result = service.search("RAG 面试", "alice")
    assert result["mode"] == "text_fallback"
    assert result["items"][0]["message_id"] == seeded["question"]["id"]

    bookmark = service.upsert_bookmark(
        "alice", seeded["answer"]["id"], note="重点复习", tags=["面试", "RAG"]
    )
    assert bookmark["message_id"] == seeded["answer"]["id"]
    assert service.list_bookmarks("alice")[0]["note"] == "重点复习"
    assert service.list_bookmarks("bob") == []

    action = service.create_action_item(
        "alice", seeded["answer"]["id"], title="补充 RAG 案例", note="写出指标变化"
    )
    assert action["source_message_id"] == seeded["answer"]["id"]
    assert service.list_action_items("bob") == []

    branch = service.create_branch(
        "alice", seeded["thread"], seeded["question"]["id"], title="RAG 面试分支"
    )
    assert branch["source_thread_id"] != branch["branch_thread_id"]
    assert len(store.list_messages(branch["branch_thread_id"], "alice")) == 1


def test_branch_cutoff_and_foreign_message_do_not_leak() -> None:
    store = ConversationStore(FakeConversationDb())
    seeded = _seed(store, "alice", "t-a")
    _seed(store, "bob", "t-b")
    alice_turn = store.next_turn("t-a", "alice")
    store.add_user_message(alice_turn["id"], "t-a", "alice", "alice-only-secret", "completed")
    service = WorkspaceTraceability(store)

    try:
        service.create_branch("alice", "t-a", "not-a-message")
    except PermissionError:
        pass
    else:
        raise AssertionError("invalid cutoff must be rejected")

    assert service.search("alice-only-secret", "bob")["items"] == []
    try:
        service.upsert_bookmark("bob", seeded["answer"]["id"], note="leak")
    except PermissionError:
        pass
    else:
        raise AssertionError("foreign message must be hidden")


def test_search_prefers_attached_semantic_backend() -> None:
    store = ConversationStore(FakeConversationDb())
    seeded = _seed(store)
    service = WorkspaceTraceability(store)

    class _SemanticBackend:
        def search(self, query, owner_id, limit):
            assert (query, owner_id, limit) == ("RAG", "alice", 7)
            return {
                "mode": "embedding",
                "query": query,
                "items": [{"message_id": seeded["answer"]["id"]}],
                "total": 1,
            }

    service.attach_semantic_search(_SemanticBackend())

    result = service.search("RAG", "alice", 7)

    assert result["mode"] == "embedding"
    assert result["items"][0]["message_id"] == seeded["answer"]["id"]


def test_search_falls_back_when_semantic_backend_is_unavailable() -> None:
    store = ConversationStore(FakeConversationDb())
    seeded = _seed(store)
    service = WorkspaceTraceability(store)

    class _BrokenSemanticBackend:
        def search(self, query, owner_id, limit):
            raise RuntimeError("qdrant unavailable")

    service.attach_semantic_search(_BrokenSemanticBackend())

    result = service.search("RAG 面试", "alice")

    assert result["mode"] == "text_fallback"
    assert result["items"][0]["message_id"] == seeded["question"]["id"]
