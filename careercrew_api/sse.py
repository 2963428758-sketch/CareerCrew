"""SSE 桥：线程+queue -> NDJSON 生成器（方案 B，零 core 改动）。

复用现有同步 ``stream_callback`` 接缝（``careercrew_ai/agents/langchain_agent.py``
run_agent 的流式适配）：agent 在后台线程跑，
callback 把 chunk 推入 queue，生成器按行 yield NDJSON 事件。

事件协议（所有流式端点统一）::

    {type:"stage", stage:"match"|"resume"|"questions"|"consult"|"synthesis"}
    {type:"chunk", text:"...", agent?: "job_matcher"}
    {type:"agent_start", agent} / {type:"agent_end", agent}   # 仅会诊
    {type:"done", content:"最终文本", opinions?: {...}}
    {type:"error", message:"..."}

响应头 ``Content-Type: application/x-ndjson``。
"""
from __future__ import annotations

import json
import queue
import threading
from collections.abc import Callable, Generator
from typing import Any

_SENTINEL = object()


def stream_agent(
    run_fn: Callable[[Callable[[str], None]], Any],
    *,
    timeout: float = 30.0,
    max_q: int = 256,
) -> Generator[str, None, None]:
    """``run_fn(callback)`` 在后台线程跑 agent；yield NDJSON 行。

    - callback = ``lambda t: q.put({"type":"chunk","text":t})``
    - 哨兵放 finally -> 生成器必终结（成败都放）
    - 30s 无 chunk = LLM 卡死兜底 -> ``{type:error}``
    - 异常 -> 最后 yield ``{type:error, message}``
    """
    q: queue.Queue = queue.Queue(maxsize=max_q)
    err: dict[str, BaseException] = {}

    def _target() -> None:
        try:
            run_fn(lambda t: q.put({"type": "chunk", "text": t}))
        except Exception as e:  # noqa: BLE001 - 桥层捕获所有, 转 error 事件
            err["exc"] = e
        finally:
            q.put(_SENTINEL)

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    while True:
        try:
            item = q.get(timeout=timeout)
        except queue.Empty:
            yield json.dumps({"type": "error", "message": f"stream timeout after {timeout}s"}, ensure_ascii=False) + "\n"
            break
        if item is _SENTINEL:
            break
        yield json.dumps(item, ensure_ascii=False) + "\n"
    if "exc" in err:
        yield json.dumps({"type": "error", "message": str(err["exc"])}, ensure_ascii=False) + "\n"
    t.join(timeout=1)


def stage_event(stage: str) -> str:
    """构造 stage 事件 NDJSON 行。"""
    return json.dumps({"type": "stage", "stage": stage}, ensure_ascii=False) + "\n"


def done_event(content: str, **extra: Any) -> str:
    """构造 done 事件 NDJSON 行。"""
    payload: dict[str, Any] = {"type": "done", "content": content}
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False) + "\n"


def error_event(message: str) -> str:
    """构造 error 事件 NDJSON 行。"""
    return json.dumps({"type": "error", "message": message}, ensure_ascii=False) + "\n"
