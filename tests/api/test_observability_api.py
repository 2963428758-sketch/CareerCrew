"""T1.4 API 层观测断言：FakeRuntime 流一个带 usage/tool_call/retrieval 的假 agent 结果，
断言 agent_runs 行 tokens/latency、tool_calls/retrievals 行存在且已脱敏截断。"""
from __future__ import annotations

import json

import pytest


@pytest.mark.web
def test_knowledge_ask_persists_observability(client, fake_runtime):
    secret = "sk-" + "A" * 40
    fake_runtime.knowledge_observability = {
        "input_tokens": 320,
        "output_tokens": 14,
        "total_tokens": 334,
        "langsmith_run_id": "ls-obs-1",
        "tool_calls": [
            {
                "tool_name": "rag_query",
                "input_redacted": {"query": f"密码 {secret}"},
                "output_summary": f"命中 token {secret} 与很长 {"长" * 200}",
                "status": "completed",
                "duration_ms": 42,
                "error_type": None,
                "error_summary": None,
            },
        ],
        "retrievals": [
            {
                "query_index": 0,
                "query_text_redacted": f"问题含 api_key={secret} 以及 {"查" * 200}",
                "scope": "all",
                "document_id": "doc-note",
                "chunk_id": None,
                "recall_score": 0.91,
                "used_in_final_context": True,
            },
        ],
    }
    resp = client.post("/api/knowledge/ask", json={"question": "RAG 的检索流程？"})
    assert resp.status_code == 200
    lines = [l for l in resp.text.strip().split("\n") if l.strip()]
    events = [json.loads(l) for l in lines]
    assert events[-1]["type"] == "done"

    # 断言 run 行 tokens / langsmith / latency
    store = fake_runtime.conversation_store
    fake_runtime.settings = getattr(fake_runtime, "settings", None)
    run_id = events[-1]["run_id"]
    run = store._db.get_run("u_001", run_id)
    assert run["input_tokens"] == 320
    assert run["output_tokens"] == 14
    assert run["total_tokens"] == 334
    assert run["langsmith_run_id"] == "ls-obs-1"
    assert run["latency_ms"] is not None
    assert run["status"] == "completed"

    # 断言 tool_call / retrieval 行 + 脱敏截断
    calls = [c for c in store._db._tool_calls.values() if c["run_id"] == run_id]
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "rag_query"
    assert calls[0]["duration_ms"] == 42
    assert secret not in str(calls[0]["input_redacted"])
    assert "[REDACTED]" in str(calls[0]["input_redacted"])
    assert secret not in calls[0]["output_summary"]
    assert len(calls[0]["output_summary"]) <= 220

    rets = [r for r in store._db._retrievals.values() if r["run_id"] == run_id]
    assert len(rets) == 1
    assert rets[0]["document_id"] == "doc-note"
    assert rets[0]["recall_score"] == 0.91
    assert rets[0]["used_in_final_context"] is True
    assert secret not in rets[0]["query_text_redacted"]
    assert "[REDACTED]" in rets[0]["query_text_redacted"]
    assert len(rets[0]["query_text_redacted"]) <= 220
