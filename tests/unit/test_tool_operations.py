from __future__ import annotations

from types import SimpleNamespace

from careercrew_core.conversation.db import FakeConversationDb
from careercrew_core.conversation.store import ConversationStore
from careercrew_core.tools.operations import ToolOperationsCenter


def _settings():
    return SimpleNamespace(tools=SimpleNamespace(
        registry=SimpleNamespace(internal=["rag_query", "submit_application"], mcp=["mcp_jobs"]),
        hitl=SimpleNamespace(requires_confirmation=["submit_application"]),
    ))


def test_tool_center_reports_policy_effective_tools_and_redacted_history() -> None:
    store = ConversationStore(FakeConversationDb())
    store.ensure_conversation("tool-thread", "alice", "chat")
    turn = store.next_turn("tool-thread", "alice")
    store.add_user_message(turn["id"], "tool-thread", "alice", "查资料", "completed")
    assistant = store.add_assistant_message(turn["id"], "tool-thread", "alice", "完成", None, None)
    run = store.start_run(
        "tool-thread", turn["id"], assistant["id"], "alice", "chat", "planner", "model",
    )
    store._db.insert_tool_call("call-1", run["id"], "rag_query", {
        "status": "failed", "duration_ms": 20, "error_type": "TimeoutError",
        "input_redacted": {"secret": "must-not-leak"}, "error_summary": "超时",
    })
    center = ToolOperationsCenter(store, _settings())

    status = center.status("chat")
    assert any(item["id"] == "rag_query" and item["health"] == "ready" for item in status)
    center.set_policy("admin", "rag_query", False, "维护")
    assert "rag_query" not in center.effective_tools("chat", None)
    history = center.call_history("alice")
    assert history[0]["failure_category"] == "timeout"
    assert history[0]["error_summary"] == "失败类别：timeout"
    assert "must-not-leak" not in str(history)
    assert center.audit("admin")[0]["tool_id"] == "rag_query"


def test_tool_center_hides_foreign_history() -> None:
    store = ConversationStore(FakeConversationDb())
    center = ToolOperationsCenter(store, _settings())
    assert center.call_history("bob") == []
