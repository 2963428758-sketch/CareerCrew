from __future__ import annotations

import numpy as np
import pytest

from careercrew_ai.embedding.base_embedding import BaseEmbedding, EmbeddingOutput
from careercrew_ai.vector_store.base_vector_store import FakeVectorStore
from careercrew_core.workspace.semantic_search import ConversationSemanticSearch


class _KeywordEmbedding(BaseEmbedding):
    """Deterministic semantic stand-in: words map to stable dense axes."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts: list[str]) -> EmbeddingOutput:
        self.calls.append(list(texts))
        dense = np.zeros((len(texts), 3), dtype=np.float32)
        for index, text in enumerate(texts):
            lowered = text.casefold()
            if "distributed" in lowered or "分布式" in lowered:
                dense[index, 0] = 1.0
            elif "retrieval" in lowered or "召回" in lowered:
                dense[index, 1] = 1.0
            else:
                dense[index, 2] = 1.0
        return EmbeddingOutput(dense=dense)


def _message(message_id: str, owner_id: str, content: str, *, deleted_at=None) -> dict:
    return {
        "id": message_id,
        "thread_id": f"thread-{owner_id}",
        "turn_id": f"turn-{message_id}",
        "user_id": owner_id,
        "role": "user",
        "content": content,
        "status": "completed",
        "created_at": "2026-09-10T10:00:00+00:00",
        "deleted_at": deleted_at,
        "thread_title": f"{owner_id} thread",
    }


def test_sync_upserts_only_changed_owned_messages() -> None:
    embedding = _KeywordEmbedding()
    vector_store = FakeVectorStore(None)
    index = ConversationSemanticSearch(embedding, vector_store, lambda _owner: [])
    rows = [_message("m-1", "alice", "distributed systems")]

    index.sync("alice", rows)
    first_call_count = len(embedding.calls)
    index.sync("alice", rows)

    assert vector_store.count({"owner_user_id": "alice"}) == 1
    assert len(embedding.calls) == first_call_count

    rows[0]["content"] = "retrieval quality"
    index.sync("alice", rows)

    assert len(embedding.calls) == first_call_count + 1
    assert vector_store.get_by_ids(["m-1"], {"owner_user_id": "alice"})[0].text == "retrieval quality"


def test_search_applies_owner_filter_and_returns_embedding_mode() -> None:
    embedding = _KeywordEmbedding()
    vector_store = FakeVectorStore(None)
    rows = [
        _message("alice-1", "alice", "distributed systems interview"),
        _message("bob-1", "bob", "distributed systems secret"),
    ]
    index = ConversationSemanticSearch(
        embedding, vector_store, lambda owner: [row for row in rows if row["user_id"] == owner]
    )

    result = index.search("distributed architecture", "alice", 10)

    assert result["mode"] == "embedding"
    assert result["total"] == 1
    assert [item["message_id"] for item in result["items"]] == ["alice-1"]
    assert vector_store.count({"owner_user_id": "bob"}) == 0


def test_search_drops_stale_vector_points_and_deleted_messages() -> None:
    embedding = _KeywordEmbedding()
    vector_store = FakeVectorStore(None)
    rows = [_message("m-1", "alice", "distributed systems")]
    index = ConversationSemanticSearch(embedding, vector_store, lambda _owner: rows)

    assert index.search("distributed", "alice")["items"]

    rows.clear()
    assert index.search("distributed", "alice")["items"] == []
    assert vector_store.count({"owner_user_id": "alice"}) == 0


def test_semantic_search_surfaces_embedding_failures_for_api_fallback() -> None:
    class _BrokenEmbedding(_KeywordEmbedding):
        def encode(self, texts: list[str]) -> EmbeddingOutput:
            raise RuntimeError("embedding unavailable")

    index = ConversationSemanticSearch(
        _BrokenEmbedding(),
        FakeVectorStore(None),
        lambda _owner: [_message("m-1", "alice", "distributed systems")],
    )

    with pytest.raises(RuntimeError, match="embedding unavailable"):
        index.search("distributed", "alice")
