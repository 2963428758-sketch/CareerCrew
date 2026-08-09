"""Phase 3: interview API 测试。"""
from __future__ import annotations

import json

import pytest


@pytest.mark.web
def test_questions_stream(client, fake_runtime):
    """出题流式：stage=questions + chunk + done。"""
    fake_runtime.interview_output = "1. 什么是 RAG？\n2. 如何优化召回？"
    resp = client.post("/api/interview/questions", json={"topic": "RAG"})
    assert resp.status_code == 200
    events = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
    assert events[0] == {"type": "stage", "stage": "questions"}
    chunks = [e for e in events if e["type"] == "chunk"]
    assert "".join(c["text"] for c in chunks) == fake_runtime.interview_output
    assert events[-1]["type"] == "done"


@pytest.mark.web
def test_score(client, fake_runtime):
    """评分 -> {score, feedback}。"""
    resp = client.post("/api/interview/score", json={
        "question": "什么是 RAG？",
        "answer": "RAG 是检索增强生成…",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "score" in data
    assert "feedback" in data
    assert data["score"] == fake_runtime.score_result["score"]


@pytest.mark.web
def test_record(client):
    """记录面试 QA 到记忆。"""
    resp = client.post("/api/interview/record", json={
        "entries": [{"q": "问题1", "a": "回答1", "score": 8}],
    })
    assert resp.status_code == 200
    assert resp.json()["saved"] == 1


@pytest.mark.web
def test_questions_default_topic(client):
    """topic 留空 -> 随机出题。"""
    resp = client.post("/api/interview/questions", json={})
    assert resp.status_code == 200
