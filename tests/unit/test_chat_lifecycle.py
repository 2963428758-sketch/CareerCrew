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


def test_finish_turn_persists_metadata(store):
    ctx = _begin(store)
    finish_turn(store, ctx, "回答", metadata={"sources": [{"doc": "note"}]})
    asst = [m for m in store.list_messages("t-1", "u_1") if m["role"] == "assistant"][0]
    assert asst["metadata"] == {"sources": [{"doc": "note"}]}


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


def test_finish_turn_writes_tokens_and_langsmith(store):
    """finish_turn 收尾时把 tokens/langsmith_run_id 写回 run 行。"""
    ctx = _begin(store)
    finish_turn(
        store, ctx, "回答",
        input_tokens=100, output_tokens=50, total_tokens=150,
        langsmith_run_id="ls-9",
    )
    run = store._db.get_run("u_1", ctx.run_id)
    assert run["input_tokens"] == 100
    assert run["output_tokens"] == 50
    assert run["total_tokens"] == 150
    assert run["langsmith_run_id"] == "ls-9"


def test_finish_turn_batch_writes_retrievals_and_tool_calls(store):
    """finish_turn 批量写 retrieval / tool_call 行（脱敏截断后）。"""
    ctx = _begin(store)
    finish_turn(
        store, ctx, "回答",
        retrievals=[
            {
                "query_index": 0, "query_text_redacted": "RAG 检索流程",
                "scope": "resume", "document_id": "doc-1", "chunk_id": "c1",
                "recall_score": 0.9, "used_in_final_context": True,
            },
        ],
        tool_calls=[
            {
                "tool_name": "rag_query", "input_redacted": {"query": "检索流程"},
                "output_summary": "命中 3 条", "status": "completed", "duration_ms": 12,
            },
        ],
    )
    run = store._db.get_run("u_1", ctx.run_id)
    # retrieval / tool_call 行在 FakeConversationDb 的内存 dict 里
    rets = [r for r in store._db._retrievals.values() if r["run_id"] == ctx.run_id]
    calls = [c for c in store._db._tool_calls.values() if c["run_id"] == ctx.run_id]
    assert len(rets) == 1
    assert rets[0]["document_id"] == "doc-1"
    assert rets[0]["query_index"] == 0
    assert rets[0]["used_in_final_context"] is True
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "rag_query"
    assert calls[0]["duration_ms"] == 12


def test_finish_turn_redacts_and_truncates_sensitive_inputs(store):
    """红action：retrieval query 与 tool_call input/output 不落完整明文/秘密。"""
    ctx = _begin(store)
    secret = "sk-" + "A" * 40
    long_query = "查一下" + "很长的查询内容" * 100
    finish_turn(
        store, ctx, "回答",
        retrievals=[
            {"query_index": 0, "query_text_redacted": f"问题含密码 api_key={secret} 与 {long_query}"},
        ],
        tool_calls=[
            {
                "tool_name": "rag_query",
                "input_redacted": {"query": f"密码 {secret}，正文：{long_query}"},
                "output_summary": f"输出含 token {secret} 后面跟着 {long_query}",
                "status": "completed",
            },
        ],
    )
    rets = [r for r in store._db._retrievals.values() if r["run_id"] == ctx.run_id]
    calls = [c for c in store._db._tool_calls.values() if c["run_id"] == ctx.run_id]
    assert secret not in rets[0]["query_text_redacted"]
    assert "[REDACTED]" in rets[0]["query_text_redacted"]
    assert len(rets[0]["query_text_redacted"]) <= 220  # 截断 + 后缀
    # tool_call input 逐值脱敏 + output_summary 脱敏截断
    assert secret not in str(calls[0]["input_redacted"])
    assert "[REDACTED]" in str(calls[0]["input_redacted"])
    assert secret not in calls[0]["output_summary"]
    assert len(calls[0]["output_summary"]) <= 220


def test_finish_turn_redacts_list_of_dict_inputs(store):
    """红action：list 内嵌套 dict（含 list）同样递归脱敏，秘密不落库。"""
    ctx = _begin(store)
    secret = "sk-" + "B" * 40
    finish_turn(
        store, ctx, "回答",
        tool_calls=[
            {
                "tool_name": "search",
                "input_redacted": {
                    "items": [
                        {"api_key": secret, "count": 3},
                        {"nested": [{"token": secret}]},
                    ],
                    "notes": ["list 内字符串 {secret}", 42],
                },
                "output_summary": "ok",
                "status": "completed",
            },
        ],
    )
    calls = [c for c in store._db._tool_calls.values() if c["run_id"] == ctx.run_id]
    persisted = str(calls[0]["input_redacted"])
    assert secret not in persisted
    assert "[REDACTED]" in persisted
    # 结构与非字符串叶子保留
    assert calls[0]["input_redacted"]["items"][0]["count"] == 3
    assert calls[0]["input_redacted"]["notes"][1] == 42


def test_turn_context_langsmith_run_id_default_none(store):
    ctx = _begin(store)
    assert ctx.langsmith_run_id is None


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


def test_begin_turn_passes_versions_to_run_and_turncontext(store):
    """T1.5：begin_turn 传入的 prompt/agent 版本落到 run 行与 TurnContext。"""
    ctx = begin_turn(
        store, thread_id="t-1", user_id="u_1", module="chat",
        agent_id="career_planner", user_text="你好", model="deepseek-v4",
        prompt_version="sha256:" + "a" * 64,
        agent_version="fc4a5f187e5471da41987d2d1a45016047ac92b2",
    )
    assert ctx.prompt_version == "sha256:" + "a" * 64
    assert ctx.agent_version == "fc4a5f187e5471da41987d2d1a45016047ac92b2"
    run = store._db.get_run("u_1", ctx.run_id)
    assert run["prompt_version"] == "sha256:" + "a" * 64
    assert run["agent_version"] == "fc4a5f187e5471da41987d2d1a45016047ac92b2"
    done = ctx.done_fields()
    assert done["prompt_version"] == "sha256:" + "a" * 64
    assert done["agent_version"] == "fc4a5f187e5471da41987d2d1a45016047ac92b2"


def test_rag_query_retrievals_labels_non_sink_rows_auto():
    """非 sink 观测路径的 rag_query 检索行显式标 'auto'（T3.4 审查项 2）。

    _rag_query_retrievals 从 agent tool_call_details 里挑出 rag_query 调用生成
    retrieval 行；这些行没有强制上下文，必须显式 retrieval_source='auto'，
    不能依赖 finish_turn 的兜底默认值。
    """
    from careercrew_api.runtime import _rag_query_retrievals

    rows = _rag_query_retrievals([
        {"name": "rag_query", "args": {"query": "检索流程", "top_k": 5}},
        {"name": "read_image", "args": {"image_path": "F:/x/p.png"}},
    ])
    assert len(rows) == 1
    assert rows[0]["retrieval_source"] == "auto"
    assert rows[0]["query_text_redacted"] == "检索流程"
    assert rows[0]["query_index"] == 0


def test_finish_turn_defaults_missing_retrieval_source_to_auto(store):
    """未显式给 retrieval_source 的检索行，finish_turn 兜底为 'auto'。"""
    ctx = _begin(store)
    finish_turn(
        store, ctx, "回答",
        retrievals=[
            # mention 行（显式）
            {"query_index": 0, "query_text_redacted": "q0", "retrieval_source": "mention"},
            # sink/auto 行（显式）
            {"query_index": 1, "query_text_redacted": "q1", "retrieval_source": "auto"},
            # 非 sink 行（缺失，依赖兜底）
            {"query_index": 2, "query_text_redacted": "q2"},
        ],
    )
    rets = sorted(
        [r for r in store._db._retrievals.values() if r["run_id"] == ctx.run_id],
        key=lambda r: r["query_index"],
    )
    assert [r["retrieval_source"] for r in rets] == ["mention", "auto", "auto"]
