"""chat_lifecycle 单元测试：begin/finish/fail/cancel 状态转换与 latency 计算。"""
from __future__ import annotations

import time
from uuid import UUID

import pytest

from careercrew_api.chat_lifecycle import (
    TurnContext,
    begin_turn,
    cancel_turn,
    fail_turn,
    finish_turn,
)
from careercrew_core.conversation.db import FakeConversationDb
from careercrew_core.conversation.store import ConversationStore


@pytest.fixture
def store() -> ConversationStore:
    return ConversationStore(FakeConversationDb())


def _begin(store, thread_id="t-1", module="chat", agent_id="career_planner") -> TurnContext:
    return begin_turn(
        store, thread_id=thread_id, user_id="u_1", module=module,
        agent_id=agent_id, user_text="你好", model="deepseek-v4",
    )


def test_begin_turn_creates_four_entities(store):
    ctx = _begin(store)
    assert UUID(ctx.thread_id)
    assert UUID(ctx.turn_id)
    assert UUID(ctx.user_message_id)
    assert UUID(ctx.assistant_message_id)
    assert UUID(ctx.run_id)
    assert ctx.legacy_thread_id == "t-1"  # 非 UUID → legacy 映射

    msgs = store.list_messages("t-1", "u_1")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["status"] == "completed"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["status"] == "streaming"


def test_finish_turn_sets_content_status_and_run(store):
    ctx = _begin(store)
    finish_turn(store, ctx, "最终回答")
    msgs = store.list_messages("t-1", "u_1")
    asst = [m for m in msgs if m["role"] == "assistant"][0]
    assert asst["content"] == "最终回答"
    assert asst["status"] == "completed"
    assert asst["run_id"] == ctx.run_id
    run = store._db.get_run("u_1", ctx.run_id)
    assert run["status"] == "completed"
    assert run["latency_ms"] is not None
    assert run["finished_at"] is not None


def test_fail_turn_records_error(store):
    ctx = _begin(store)
    fail_turn(store, ctx, ValueError("bad input"))
    asst = [m for m in store.list_messages("t-1", "u_1") if m["role"] == "assistant"][0]
    assert asst["status"] == "failed"
    run = store._db.get_run("u_1", ctx.run_id)
    assert run["status"] == "failed"
    assert run["error_type"] == "ValueError"
    assert "bad input" in run["error_summary"]


def test_cancel_turn_marks_cancelled(store):
    ctx = _begin(store)
    cancel_turn(store, ctx)
    asst = [m for m in store.list_messages("t-1", "u_1") if m["role"] == "assistant"][0]
    assert asst["status"] == "cancelled"
    assert store._db.get_run("u_1", ctx.run_id)["status"] == "cancelled"


def test_latency_monotonic(store):
    ctx = _begin(store)
    t0 = ctx.latency_ms()
    time.sleep(0.01)
    assert ctx.latency_ms() >= t0


def test_done_fields_schema(store):
    ctx = _begin(store)
    fields = ctx.done_fields()
    assert set(fields) == {
        "thread_id", "turn_id", "message_id", "run_id", "model",
        "prompt_version", "agent_version", "status", "legacy_thread_id",
    }
    assert fields["status"] == "completed"
    assert fields["model"] == "deepseek-v4"
    assert fields["prompt_version"] == "unversioned"
