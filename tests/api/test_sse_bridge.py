"""Phase 1: SSE 桥测试 -- 正常流 / 抛异常 / 超时。"""
from __future__ import annotations

import json
import time

import pytest

from careercrew_api.sse import done_event, error_event, stage_event, stream_agent


@pytest.mark.web
def test_stream_normal():
    """正常流：callback 推 chunk -> 哨兵 -> 正常结束。"""
    chunks: list[str] = []

    def run_fn(cb):
        for t in ["你好", "世界", "!"]:
            cb(t)
            chunks.append(t)

    lines = list(stream_agent(run_fn, timeout=5.0))
    events = [json.loads(l) for l in lines]
    # 前 3 个是 chunk
    assert len(events) == 3
    assert all(e["type"] == "chunk" for e in events)
    assert "".join(e["text"] for e in events) == "你好世界!"


@pytest.mark.web
def test_stream_exception():
    """run_fn 抛异常 -> 最后 yield error 事件。"""
    def run_fn(cb):
        cb("部分内容")
        raise RuntimeError("agent 挂了")

    lines = list(stream_agent(run_fn, timeout=5.0))
    events = [json.loads(l) for l in lines]
    # 第一个是 chunk，最后一个是 error
    assert events[0]["type"] == "chunk"
    assert events[-1]["type"] == "error"
    assert "agent 挂了" in events[-1]["message"]


@pytest.mark.web
def test_stream_timeout():
    """30s 无 chunk = 超时兜底 -> error 事件。用极短 timeout 模拟。"""
    def run_fn(cb):
        time.sleep(3)  # 卡住，不推 chunk
        cb("太晚了")

    lines = list(stream_agent(run_fn, timeout=0.5, max_q=8))
    events = [json.loads(l) for l in lines]
    assert any(e["type"] == "error" and "timeout" in e["message"] for e in events)


@pytest.mark.web
def test_stage_done_error_events():
    """辅助函数构造的事件格式正确。"""
    s = json.loads(stage_event("match"))
    assert s == {"type": "stage", "stage": "match"}

    d = json.loads(done_event("最终结果"))
    assert d == {"type": "done", "content": "最终结果"}

    d2 = json.loads(done_event("综合", opinions={"a": "b"}))
    assert d2["opinions"] == {"a": "b"}

    e = json.loads(error_event("出错了"))
    assert e == {"type": "error", "message": "出错了"}


@pytest.mark.web
def test_stream_maxsize_backpressure():
    """maxsize 限流：队列满时丢弃可合并 chunk（非阻塞），worker 不因背压挂死。"""
    def run_fn(cb):
        for i in range(200):
            cb(f"chunk-{i}")

    g = stream_agent(run_fn, timeout=5.0, max_q=8)
    first = next(g)
    time.sleep(0.05)  # 消费者暂停：worker 填满队列后开始丢弃
    lines = [first] + list(g)
    events = [json.loads(l) for l in lines]
    assert events[0]["text"] == "chunk-0"
    assert len(events) < 200  # 有丢弃（背压生效，未阻塞 worker）
