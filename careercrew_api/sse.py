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
import logging
import os
import queue
import threading
import time
from collections.abc import Callable, Generator
from typing import Any

logger = logging.getLogger("careercrew_api.sse")

STREAM_IDLE_TIMEOUT_SECONDS = float(
    os.environ.get("CONSULT_STREAM_IDLE_TIMEOUT_SECONDS", "300")
)

# 用户可见错误里原始异常文本的截断上限（防内部路径/长堆栈刷屏与信息泄露）
_ERROR_DETAIL_MAX_CHARS = 200

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


# 前端 AbortController 只能中止浏览器的读取；在代理/同步 LLM 调用尚未返回时，
# ASGI 未必能立刻感知客户端断开。按用户和会话登记取消事件，让停止按钮额外通知
# 服务端，在当前模型调用结束后的第一个检查点阻止下一次工具或模型调用。
_active_streams: dict[tuple[str, str], CancellationEvent] = {}
_active_streams_lock = threading.Lock()


def register_stream_cancellation(user_id: str, thread_id: str) -> CancellationEvent:
    event = CancellationEvent()
    with _active_streams_lock:
        previous = _active_streams.get((user_id, thread_id))
        if previous is not None:
            previous.set()
        _active_streams[(user_id, thread_id)] = event
    return event


def cancel_registered_stream(user_id: str, thread_id: str) -> bool:
    with _active_streams_lock:
        event = _active_streams.get((user_id, thread_id))
    if event is None:
        return False
    event.set()
    return True


def unregister_stream_cancellation(user_id: str, thread_id: str, event: CancellationEvent) -> None:
    """只移除仍属于本次生成的登记，避免旧请求删掉新请求的取消句柄。"""
    with _active_streams_lock:
        key = (user_id, thread_id)
        if _active_streams.get(key) is event:
            _active_streams.pop(key, None)


def put_guaranteed(q: queue.Queue, item: Any, cancel: CancellationEvent | None = None) -> None:
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
    q: queue.Queue = queue.Queue(maxsize=max_q)
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
                        {"type": "error", "message": f"回答生成超时（等待超过 {idle:g} 秒无响应），请重试"},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                break
            if item is _SENTINEL:
                break
            yield json.dumps(item, ensure_ascii=False) + "\n"
        if "exc" in err:
            yield json.dumps({"type": "error", "message": friendly_error(err["exc"])}, ensure_ascii=False) + "\n"
    except GeneratorExit:
        cev.set()
        raise
    finally:
        t.join(timeout=1)
        if t.is_alive():
            # 协作式取消的固有窗口：worker 正卡在一次 LLM/工具调用里，
            # 会运行到下一个检查点才停（token 消耗到自然边界为止）。留痕便于
            # 排查「取消后仍有少量消耗」与高并发取消下的线程堆积。
            logger.debug("stream worker still running after client disconnect")


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


def _clip_detail(msg: str) -> str:
    """截断原始异常细节（单行化 + 限长），保留排查线索又不刷屏/泄露堆栈。"""
    one_line = " ".join(msg.split())
    if len(one_line) <= _ERROR_DETAIL_MAX_CHARS:
        return one_line
    return one_line[:_ERROR_DETAIL_MAX_CHARS] + "…"


def _trace_id() -> str:
    """当前请求关联 ID（X-Request-ID），供用户反馈时与服务端日志对账。"""
    try:
        from careercrew_api.logging_config import request_id_var

        rid = request_id_var.get("")
        return f"，追踪号 {rid}" if rid else ""
    except Exception:  # noqa: BLE001 - 取不到追踪号不影响错误提示本身
        return ""


def friendly_error(exc: BaseException) -> str:
    """把底层异常转成用户可读的中文提示。

    覆盖常见故障类：网络连接、超时、API Key、额度/限流、模型不可用、上下文过长。
    任何基础设施或供应商异常都不能把原始细节带到用户界面（其中可能包含内部路径、
    端点或实现信息）；改给可行动的通用提示 + 追踪号。已是中文的业务异常原样返回。
    """
    msg = str(exc).strip() or type(exc).__name__
    if any("\u4e00" <= ch <= "\u9fff" for ch in msg):
        return _clip_detail(msg)
    lowered = msg.lower()
    if any(k in lowered for k in ("connection", "connect", "refused", "network",
                                   "name or service not known", "unreachable")):
        return f"暂时无法连接 AI 服务，请稍后重试{_trace_id()}"
    if "timeout" in lowered or "timed out" in lowered:
        return f"AI 服务响应超时，请稍后重试{_trace_id()}"
    if any(k in lowered for k in ("api key", "apikey", "unauthorized", "authentication",
                                  "invalid token", "credentials")) or "401" in msg:
        return f"AI 服务暂时不可用，请稍后重试{_trace_id()}"
    if any(k in lowered for k in ("quota", "rate limit", "too many requests")) or "429" in msg:
        return f"AI 服务当前繁忙，请稍后重试{_trace_id()}"
    if "model" in lowered and any(k in lowered for k in ("not found", "not exist",
                                                         "not available", "does not exist")):
        return f"AI 服务暂时不可用，请稍后重试{_trace_id()}"
    if any(k in lowered for k in ("maximum context", "context length", "out of memory",
                                  "token limit")):
        return f"对话内容过长，请新开一个会话再试{_trace_id()}"
    return f"生成失败，请稍后重试{_trace_id()}"


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
