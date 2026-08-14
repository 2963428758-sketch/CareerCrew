"""知识库问答 API 测试（FakeAgent 流式）。"""
from __future__ import annotations

import json

import pytest


@pytest.mark.web
def test_knowledge_ask_stream(client, fake_runtime):
    """知识库问答：stage:knowledge -> chunk -> done。"""
    resp = client.post("/api/knowledge/ask", json={"question": "RAG 的检索流程？"})
    assert resp.status_code == 200
    lines = [l for l in resp.text.strip().split("\n") if l.strip()]
    events = [json.loads(l) for l in lines]

    # 第一个事件是 stage=knowledge
    assert events[0] == {"type": "stage", "stage": "knowledge"}

    # 有 chunk
    chunks = [e for e in events if e["type"] == "chunk"]
    assert chunks
    assert all("text" in c for c in chunks)

    # 最后是 done，content 为拼接的 chunk，且携带结构化来源（可点击查看）
    done = events[-1]
    assert done["type"] == "done"
    assert fake_runtime.knowledge_output in done["content"]
    assert done["sources"] == fake_runtime.knowledge_sources
    assert done["sources"][0]["doc"] == "note"


@pytest.mark.web
def test_knowledge_ask_empty_question(client):
    """空问题应返回 422（pydantic 校验）。"""
    resp = client.post("/api/knowledge/ask", json={"question": ""})
    assert resp.status_code == 422


@pytest.mark.web
def test_knowledge_ask_with_category(client):
    """按分类检索：category 字段可透传。"""
    resp = client.post("/api/knowledge/ask", json={
        "question": "我的学校",
        "category": "resume",
    })
    assert resp.status_code == 200
    lines = [l for l in resp.text.strip().split("\n") if l.strip()]
    events = [json.loads(l) for l in lines]
    assert events[-1]["type"] == "done"
