"""Phase 2: chat API 测试（FakeRuntime 注入）。"""
from __future__ import annotations

import json

import pytest


@pytest.mark.web
def test_match_stream(client, fake_runtime):
    """match 流式：返回 NDJSON，含 stage/chunk/done 事件。"""
    fake_runtime.match_output = "匹配到字节跳动 0.95"
    resp = client.post("/api/chat/match", json={"intent": "大模型方向找工作"})
    assert resp.status_code == 200
    assert "x-ndjson" in resp.headers.get("content-type", "")

    lines = [l for l in resp.text.strip().split("\n") if l.strip()]
    events = [json.loads(l) for l in lines]

    # 第一个事件是 stage
    assert events[0]["type"] == "stage"
    assert events[0]["stage"] == "match"

    # 中间是 chunk
    chunks = [e for e in events if e["type"] == "chunk"]
    assert len(chunks) >= 1
    assert "".join(c["text"] for c in chunks) == "匹配到字节跳动 0.95"

    # 最后是 done
    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "匹配到字节跳动 0.95"


@pytest.mark.web
def test_resume_stream(client, fake_runtime):
    """resume 流式：带跨步骤历史（thread_id 承接）。"""
    fake_runtime.resume_output = "定制简历完成"
    resp = client.post("/api/chat/resume", json={
        "jd_text": "字节跳动 大模型应用工程师",
        "thread_id": "m1",
    })
    assert resp.status_code == 200
    lines = [l for l in resp.text.strip().split("\n") if l.strip()]
    events = [json.loads(l) for l in lines]

    assert events[0]["type"] == "stage"
    assert events[0]["stage"] == "resume"
    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "定制简历完成"


@pytest.mark.web
def test_match_default_thread_id(client):
    """默认 thread_id=m1, user_id=u_001。"""
    resp = client.post("/api/chat/match", json={"intent": "找工作"})
    assert resp.status_code == 200


@pytest.mark.web
def test_match_error_handling(client, fake_runtime):
    """run_fn 抛异常 -> error 事件。"""
    fake_runtime.match_output = ""
    original = fake_runtime.run_match_stream
    fake_runtime.run_match_stream = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("测试异常"))
    resp = client.post("/api/chat/match", json={"intent": "测试"})
    lines = [l for l in resp.text.strip().split("\n") if l.strip()]
    events = [json.loads(l) for l in lines]
    assert any(e["type"] == "error" for e in events)
    fake_runtime.run_match_stream = original


@pytest.mark.web
def test_match_done_uses_final_answer_not_streamed_preamble(client, fake_runtime):
    """回归：match 流式 chunk 带中间轮开头话时，done 内容必须取最终回答。"""
    fake_runtime.match_output = "匹配到字节跳动 0.95"
    fake_runtime.stream_preamble = "好的，我先检索岗位"
    resp = client.post("/api/chat/match", json={"intent": "大模型方向找工作"})
    assert resp.status_code == 200
    events = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
    chunks = "".join(e["text"] for e in events if e["type"] == "chunk")
    assert "好的，我先检索岗位" in chunks
    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == "匹配到字节跳动 0.95"
    assert "我先检索岗位" not in events[-1]["content"]


@pytest.mark.web
def test_match_done_carries_structured_jobs_and_history_metadata(client, fake_runtime):
    """岗位卡片：成功 search_jobs 的结构化结果随 done 事件透出，并持久化到历史。"""
    fake_runtime.match_output = "找到 1 个匹配岗位"
    fake_runtime.match_jobs = [{
        "company": "测试公司", "title": "Java开发", "city": "深圳",
        "salary": "20-30K", "source": "boss", "source_label": "Boss直聘",
        "url": "https://example.com/j/1", "jd": "负责接口开发",
    }]
    resp = client.post("/api/chat/match", json={"intent": "找 Java 工作", "thread_id": "mjobs"})
    assert resp.status_code == 200
    events = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
    assert events[-1]["type"] == "done"
    assert events[-1]["jobs"] == fake_runtime.match_jobs

    # 历史恢复：assistant 消息 metadata 携带同一份 jobs
    thread_id = events[-1]["thread_id"]
    hist = client.get(f"/api/threads/{thread_id}/messages")
    assert hist.status_code == 200
    assistant = [m for m in hist.json() if m["role"] == "assistant"]
    assert assistant and (assistant[-1].get("metadata") or {}).get("jobs") == fake_runtime.match_jobs


@pytest.mark.web
def test_match_done_without_jobs_has_no_jobs_key(client, fake_runtime):
    """无结构化结果时 done 不带 jobs 键，老客户端不受影响。"""
    fake_runtime.match_jobs = []
    resp = client.post("/api/chat/match", json={"intent": "找工作", "thread_id": "mnojobs"})
    assert resp.status_code == 200
    events = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
    assert events[-1]["type"] == "done"
    assert "jobs" not in events[-1]


@pytest.mark.web
def test_plan_stream(client, fake_runtime):
    """求职对话：职业规划师主理，stage=planning + chunk + done。"""
    fake_runtime.planner_output = "规划完成：冲刺字节/阿里，匹配美团/腾讯"
    resp = client.post("/api/chat/plan", json={"intent": "大模型方向，帮我规划求职"})
    assert resp.status_code == 200
    events = [json.loads(l) for l in resp.text.strip().split("\n") if l.strip()]
    assert events[0]["type"] == "stage"
    assert events[0]["stage"] == "planning"
    chunks = "".join(e["text"] for e in events if e["type"] == "chunk")
    assert chunks == fake_runtime.planner_output
    assert events[-1]["type"] == "done"
    assert events[-1]["content"] == fake_runtime.planner_output
