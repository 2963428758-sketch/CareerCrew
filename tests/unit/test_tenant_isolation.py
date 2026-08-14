"""Authentication-principal tenant boundaries at internal persistence seams."""
from __future__ import annotations

from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from careercrew_ai.vector_store.base_vector_store import VectorRecord
from careercrew_ai.vector_store.qdrant_store import QdrantStore
from careercrew_api.runtime import CareerCrewRuntime
from careercrew_core.memory.db import FakeMemoryDb
from careercrew_core.memory.semantic import SemanticFactStore
from careercrew_core.memory.threads import ThreadStore
from careercrew_core.state.checkpointer import tenant_checkpoint_config
from careercrew_core.state.settings import Settings


def test_thread_store_keys_same_public_thread_by_user() -> None:
    store = ThreadStore(FakeMemoryDb())

    store.upsert("u_alice", "shared", title="Alice", module="chat")
    store.upsert("u_bob", "shared", title="Bob", module="resume")

    assert store.get("u_alice", "shared")["title"] == "Alice"
    assert store.get("u_bob", "shared")["title"] == "Bob"
    assert [row["thread_id"] for row in store.list("u_alice")] == ["shared"]
    assert store.delete("u_alice", "shared") == 1
    assert store.get("u_alice", "shared") is None
    assert store.get("u_bob", "shared")["title"] == "Bob"


def test_runtime_cycle_cache_keys_by_user_and_public_thread() -> None:
    runtime = CareerCrewRuntime()
    runtime._initialized = True
    runtime.memory_db = FakeMemoryDb()
    runtime.fact_store = SemanticFactStore(runtime.memory_db, "u_001")
    runtime.new_job_matcher = lambda cb=None, episodic=None: object()
    runtime.new_resume_advisor = lambda cb=None, episodic=None: object()

    alice = runtime.get_cycle("shared", "u_alice")
    bob = runtime.get_cycle("shared", "u_bob")

    assert alice is runtime.get_cycle("shared", "u_alice")
    assert alice is not bob
    assert alice._user_id == "u_alice" and alice._thread_id == "shared"
    assert bob._user_id == "u_bob" and bob._thread_id == "shared"


def test_qdrant_physical_ids_do_not_collide_for_same_tenant_local_id(
    valid_config_data: dict,
) -> None:
    settings = Settings.model_validate(valid_config_data)
    store = QdrantStore(settings, collection_name="tenant-id-collision")
    store.upsert([
        VectorRecord(
            id="e_001", dense=[1.0] * 1024, text="Alice secret",
            metadata={
                "user_id": "u_alice", "type": "note", "image_path": "F:/alice.png",
            },
        ),
        VectorRecord(
            id="e_001", dense=[1.0] * 1024, text="Bob secret",
            metadata={"user_id": "u_bob", "type": "note"},
        ),
    ])

    assert store.count() == 2
    alice = store.query([1.0] * 1024, filters={"user_id": "u_alice"})
    bob = store.query([1.0] * 1024, filters={"user_id": "u_bob"})
    assert [(row.id, row.text) for row in alice] == [("e_001", "Alice secret")]
    assert [(row.id, row.text) for row in bob] == [("e_001", "Bob secret")]
    assert store.get_by_ids(["e_001"], filters={"user_id": "u_alice"})[0].text == "Alice secret"
    assert store.get_by_ids(["e_001"], filters={"user_id": "u_bob"})[0].text == "Bob secret"
    assert store.metadata_exists({"user_id": "u_alice", "image_path": "F:/alice.png"})
    assert not store.metadata_exists({"user_id": "u_bob", "image_path": "F:/alice.png"})


class _CounterState(TypedDict):
    count: int


def test_compiled_graph_checkpoint_state_is_namespaced_by_authenticated_user() -> None:
    graph = StateGraph(_CounterState)
    graph.add_node("increment", lambda state: {"count": state["count"] + 1})
    graph.add_edge(START, "increment")
    graph.add_edge("increment", END)
    app = graph.compile(checkpointer=MemorySaver())

    alice_cfg = tenant_checkpoint_config("u_alice", "shared")
    bob_cfg = tenant_checkpoint_config("u_bob", "shared")
    assert alice_cfg["configurable"]["thread_id"] != bob_cfg["configurable"]["thread_id"]

    assert app.invoke({"count": 0}, config=alice_cfg)["count"] == 1
    assert app.invoke({"count": 40}, config=bob_cfg)["count"] == 41
    assert app.invoke({}, config=alice_cfg)["count"] == 2
    assert app.invoke({}, config=bob_cfg)["count"] == 42
