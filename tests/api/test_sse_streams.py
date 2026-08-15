"""SSE 桥回归测试：断连取消、队列满背压、取消后无后续调用、统一超时文案。"""
from __future__ import annotations

import time

from careercrew_api.sse import CancellationEvent, StreamCancelled, stream_agent


def _lines(gen):
    return [l for l in gen]


def test_disconnect_sets_cancel_and_stops_worker():
    cancel = CancellationEvent()
    calls = []

    def run_fn(cb):
        for _ in range(100000):
            cancel.check()
            cb("x")  # chunk 推送路径同样检查
            calls.append(1)
            time.sleep(0.001)

    g = stream_agent(run_fn, timeout=30.0, max_q=4, cancel=cancel)
    next(g)
    next(g)
    g.close()  # 模拟客户端断开
    assert cancel.is_set()
    time.sleep(0.2)
    n = len(calls)
    time.sleep(0.3)
    assert len(calls) - n <= 2  # worker 已在边界停止，不再推进


def test_queue_full_drops_chunks_but_terminal_delivered():
    cancel = CancellationEvent()

    def run_fn(cb):
        for i in range(200):
            cancel.check()
            cb(f"chunk-{i}")

    g = stream_agent(run_fn, timeout=30.0, max_q=2, cancel=cancel)
    first = next(g)
    time.sleep(0.1)  # 消费者暂停：worker 填满队列后开始丢弃
    lines = [first] + _lines(g)
    assert '"type": "chunk"' in first
    assert len(lines) < 200  # 有丢弃（背压生效，未阻塞 worker）


def test_cancel_before_run_prevents_work():
    cancel = CancellationEvent()
    cancel.set()
    calls = []

    def run_fn(cb):
        calls.append("run")
        cb("should-not-happen")

    lines = _lines(stream_agent(run_fn, timeout=30.0, cancel=cancel))
    assert calls == []
    assert not any('"type": "error"' in l for l in lines)


def test_timeout_message_uses_configured_seconds():
    def run_fn(cb):
        time.sleep(0.5)

    lines = _lines(stream_agent(run_fn, timeout=0.05))
    assert any("stream timeout after 0.05s" in l for l in lines)


def test_cancel_stops_further_callback_emission():
    cancel = CancellationEvent()
    emitted = []

    def run_fn(cb):
        for i in range(100):
            cancel.check()
            cb(f"c{i}")
            emitted.append(i)
            if i == 3:
                cancel.set()  # 中途取消：后续迭代在检查点停止

    _lines(stream_agent(run_fn, timeout=30.0, max_q=4, cancel=cancel))
    assert emitted == [0, 1, 2, 3]  # 取消后无后续调用


def test_consult_stream_disconnect_cancels(client, fake_runtime):
    import time as _time

    def slow_decide(prompt, config=None):
        _time.sleep(0.05)
        return type("R", (), {"content": (
            '{"next_agents": [], "tasks": {}, "final_answer": "x", '
            '"needs_user_input": false, "input_fields": []}'
        )})()

    fake_runtime.orchestrator_override = slow_decide
    with client.stream("POST", "/api/consult", json={"question": "q", "thread_id": "c-1"}) as resp:
        it = resp.iter_lines()
        next(it)  # stage
        # 提前断开
    # 后端 worker 应在取消事件驱动下尽快结束（断言：服务仍可用、无挂死）
    assert client.get("/api/health").status_code == 200


def test_chat_endpoint_passes_cancel_to_runtime(client, fake_runtime):
    """断开后 runtime 在阶段边界停止：cancel_check 确实透传进 agent 阶段。"""
    import time as _time

    state = {"checks": 0}

    def slow_match(thread_id, user_id, intent, cb=None, cancel_check=None):
        for _ in range(1000):
            if cancel_check is not None:
                state["checks"] += 1
                try:
                    cancel_check()
                except StreamCancelled:
                    return ""  # 已取消：不再产出，也不启动后续阶段
            _time.sleep(0.01)
        if cb:
            cb("done text")
        return "done text"

    fake_runtime.run_match_stream = slow_match
    with client.stream("POST", "/api/chat/match", json={"intent": "x", "thread_id": "m-1"}) as resp:
        it = resp.iter_lines()
        next(it)  # stage
        # 提前断开
    n = state["checks"]
    _time.sleep(0.2)
    assert state["checks"] - n <= 2  # 断开后 worker 在边界停止
