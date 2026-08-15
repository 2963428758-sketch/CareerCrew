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

Task 3 增强（取消 / 背压 / 统一超时）：
- ``CancellationEvent``：协作式取消。生成器被关闭（客户端断开 / 前端 abort /
  停止生成）时 set；worker 在每次推送与阶段边界 ``check()``，取消后不再发起
  后续 LLM / 工具 / 会诊阶段。
- 背压：chunk 事件 ``put_nowait``，队列满时丢弃并计数（可合并文本块）；
  哨兵与 error/done 等终态事件走 ``put_guaranteed``（轮询重试 + 取消感知），
  终态事件不永久阻塞、不静默丢失。
- 统一空闲超时：``CONSULT_STREAM_IDLE_TIMEOUT_SECONDS``（默认 300），
  所有流式端点共用，用户可见提示用同一真实秒数。
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections.abc import Callable, Generator
from typing import Any

STREAM_IDLE_TIMEOUT_SECONDS = float(
    os.environ.get("CONSULT_STREAM_IDLE_TIMEOUT_SECONDS", "300")
)

_SENTINEL = object()


class StreamCancelled(Exception):
    """协作式取消信号：worker 在检查点抛出，不再推进后续阶段。"""


class CancellationEvent:
    """共享取消事件（客户端断开 / 停止生成时 set）。"""

    def __init__(self) -> None:
        self._e = threading.Event()

    def set(self) -> None:
        self._e.set()

    def is_set(self) -> bool:
        return self._e.is_set()

    def check(self) -> None:
        """协作式取消检查点：已取消则抛 StreamCancelled。"""
        if self._e.is_set():
            raise StreamCancelled()


def put_guaranteed(q: "queue.Queue", item: Any, cancel: CancellationEvent | None = None) -> None:
    """终态事件受控投递：队列满时轮询重试；取消已设置则放弃（消费者已消失）。"""
    while True:
        try:
            q.put_nowait(item)
            return
        except queue.Full:
            if cancel is not None and cancel.is_set():
                return
            time.sleep(0.05)


def stream_agent(
    run_fn: Callable[[Callable[[str], None]], Any],
    *,
    timeout: float | None = None,
    max_q: int = 256,
    cancel: CancellationEvent | None = None,
) -> Generator[str, None, None]:
    """``run_fn(callback)`` 在后台线程跑 agent；yield NDJSON 行。

    - callback = 非阻塞 chunk 推送（队列满丢弃，不阻塞 worker）
    - 哨兵放 finally -> 生成器必终结（成败都放）
    - 空闲超时默认 ``STREAM_IDLE_TIMEOUT_SECONDS`` -> ``{type:error}``
    - 异常 -> 最后 yield ``{type:error, message}``
    - 生成器关闭（客户端断开）-> ``cancel.set()``，worker 在检查点停止
    """
    q: "queue.Queue" = queue.Queue(maxsize=max_q)
    err: dict[str, BaseException] = {}
    dropped = [0]
    cev = cancel or CancellationEvent()

    def _put_chunk(text: str) -> None:
        cev.check()
        try:
            q.put_nowait({"type": "chunk", "text": text})
        except queue.Full:
            dropped[0] += 1  # 可合并文本块：丢弃不阻塞

    def _target() -> None:
        try:
            cev.check()
            run_fn(_put_chunk)
        except StreamCancelled:
            pass  # 协作式取消：不再发起后续 LLM/工具调用
        except Exception as e:  # noqa: BLE001 - 桥层捕获所有, 转 error 事件
            err["exc"] = e
        finally:
            put_guaranteed(q, _SENTINEL, cev)

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    idle = timeout if timeout is not None else STREAM_IDLE_TIMEOUT_SECONDS
    try:
        while True:
            try:
                item = q.get(timeout=idle)
            except queue.Empty:
                yield (
                    json.dumps(
                        {"type": "error", "message": f"stream timeout after {idle}s"},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                break
            if item is _SENTINEL:
                break
            yield json.dumps(item, ensure_ascii=False) + "\n"
        if "exc" in err:
            yield json.dumps({"type": "error", "message": str(err["exc"])}, ensure_ascii=False) + "\n"
    except GeneratorExit:
        cev.set()
        raise
    finally:
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


def turn_done_fields(turn) -> dict:
    """把 TurnContext（或有 done_fields 方法的对象）转为 §9 done 事件附加字段。

    turn 为 None（生命周期未接线 / 存储降级）时返回空 dict，done 事件退化为仅 content，
    兼容 FakeRuntime 无对话存储的场景。
    """
    if turn is None:
        return {}
    if hasattr(turn, "done_fields"):
        return turn.done_fields()
    if isinstance(turn, dict):
        return dict(turn)
    return {}
