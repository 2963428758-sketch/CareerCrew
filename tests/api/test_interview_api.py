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


@pytest.mark.web
def test_chat_first_question(client, fake_runtime):
    """对话式面试（无历史）：stage + chunk + done，不带评分。"""
    fake_runtime.interview_output = "请讲讲你对 RAG 的理解"
    resp = client.post("/api/interview/chat", json={"topic": "RAG", "messages": []})
    assert resp.status_code == 200
    events = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
    assert events[0]["type"] == "stage"
    chunks = [e for e in events if e["type"] == "chunk"]
    assert "".join(c["text"] for c in chunks) == fake_runtime.interview_output
    done = events[-1]
    assert done["type"] == "done"
    assert "score" not in done


@pytest.mark.web
def test_chat_score_extracted(client, fake_runtime):
    """用户回答后 -> done 事件携带 score/feedback。"""
    fake_runtime.interview_output = (
        "## 分数：8.5/10\n### 诊断\n- 结构清晰\n### 下一题\n请说说缓存一致性"
    )
    resp = client.post("/api/interview/chat", json={
        "topic": "RAG",
        "messages": [
            {"role": "assistant", "content": "请讲讲你对 RAG 的理解"},
            {"role": "user", "content": "RAG 是检索增强生成…"},
        ],
    })
    assert resp.status_code == 200
    events = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
    done = events[-1]
    assert done["type"] == "done"
    assert done["score"] == 8.5
    assert "结构清晰" in done["feedback"]
