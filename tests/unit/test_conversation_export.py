"""conversation/export 纯函数单元测试：MD/JSON 内容形状 + 敏感字段红线。"""
from __future__ import annotations

import pytest

from careercrew_core.conversation.export import build_json, build_markdown


CONV = {"id": "u-1", "title": "求职咨询", "module": "chat", "created_at": "2026-01-01T00:00:00Z"}

MESSAGES = [
    {"id": "m1", "role": "user", "content": "帮我找大模型岗位", "status": "completed"},
    {
        "id": "m2", "role": "assistant", "content": "推荐字节/阿里",
        "metadata": {"sources": [
            {"doc": "note", "source": "data/note.md", "score": 0.9, "text": "RAG"},
        ]},
    },
]

RUNS = [
    {"model": "deepseek-v4", "prompt_version": "sha256:abc", "agent_version": "1",
     "latency_ms": 120, "input_tokens": 100, "error_summary": "boom"},
]


def test_markdown_has_title_user_assistant_sources():
    md = build_markdown(CONV, MESSAGES)
    assert "# 求职咨询" in md
    assert "## User" in md
    assert "帮我找大模型岗位" in md
    assert "## Assistant" in md
    assert "### Sources" in md
    assert "- note" in md


def test_markdown_skips_unknown_roles():
    msgs = MESSAGES + [{"id": "m3", "role": "system", "content": "SYSTEM PROMPT SECRET"}]
    md = build_markdown(CONV, msgs)
    assert "SYSTEM PROMPT" not in md


def test_json_has_thread_messages_sources_runs():
    body = build_json(CONV, MESSAGES, RUNS)
    assert body["thread"]["title"] == "求职咨询"
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][1]["sources"][0]["doc"] == "note"
    assert body["sources"][0]["doc"] == "note"
    run = body["runs"][0]
    assert run["model"] == "deepseek-v4"
    assert run["prompt_version"] == "sha256:abc"
    assert run["agent_version"] == "1"
    assert run["latency_ms"] == 120
    # 白名单之外字段不得泄漏（input_tokens / error_summary 被剔除）
    assert "input_tokens" not in run
    assert "error_summary" not in run


def test_json_omits_run_internal_fields():
    body = build_json(CONV, MESSAGES, RUNS)
    assert "langsmith_run_id" not in body["runs"][0]
    assert "run_id" not in body["messages"][0]


def test_export_rejects_sensitive_content():
    # 内容里混入疑似 token/secret 时拒绝导出（防御性红线）
    msgs = [{"id": "m1", "role": "assistant", "content": "我的 api_key=sk-abc123"}]
    with pytest.raises(ValueError):
        build_json(CONV, msgs, [])
    with pytest.raises(ValueError):
        build_markdown(CONV, msgs)


def test_markdown_empty_conversation():
    md = build_markdown(CONV, [])
    assert "# 求职咨询" in md


def test_json_empty_runs_default():
    body = build_json(CONV, MESSAGES, [])
    assert body["runs"] == []
