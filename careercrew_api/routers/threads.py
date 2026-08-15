"""threads 路由：对话会话（conversation 表，Source of Truth）创建与消息恢复。

- POST /api/threads           新建会话（服务端生成 UUID；兼容旧 thread_id 形参）
- GET  /api/threads/{thread_id}/messages  按 turn sequence 返回全部消息（§37 状态恢复）
- POST /api/messages/{message_id}/regenerate  重新生成最后一条 assistant 消息（§34/§38）

与 data.py 的 memory 线程（GET/PATCH/DELETE /api/threads，sidebar 列表）分工：
本路由负责 conversation 表（稳定 ID 的 Source of Truth）；创建时同时登记 memory
线程元数据（sidebar 可见），保持 episodic 双写与既有前端行为不变。
"""
from __future__ import annotations

import json
from collections.abc import Generator

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from careercrew_api.auth.dependencies import CurrentUser
from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import (
    CareerCrewRuntime,
    RegenerateConflictError,
    ResourceNotFoundError,
)
from careercrew_api.sse import (
    CancellationEvent,
    done_event,
    error_event,
    stage_event,
    stream_agent,
    turn_done_fields,
)
from careercrew_core.conversation.store import OwnershipError

router = APIRouter()

_KNOWN_MODULES = ("matcher", "resume", "chat", "knowledge", "consult", "interview")


class ThreadCreateRequest(BaseModel):
    module: str = "chat"
    title: str | None = None
    retrieval_scope: dict | None = None
    # 兼容旧 memory 线程登记（前端传 t-xxx）；缺省时服务端生成 UUID
    thread_id: str | None = None

    @field_validator("module")
    @classmethod
    def _module_known(cls, v: str) -> str:
        if v not in _KNOWN_MODULES:
            raise ValueError(f"module 必须为 {'/'.join(_KNOWN_MODULES)} 之一")
        return v


@router.post("/threads")
def create_thread(req: ThreadCreateRequest, current_user: CurrentUser,
                  rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """新建会话：conversation 表登记（服务端生成 UUID 或复用 legacy），并存 memory 线程元数据。"""
    user_id = current_user["id"]
    rt._ensure_heavy()
    # 缺省 thread_id → 服务端生成 UUID；显式提供则按 legacy 映射复用/新建
    from careercrew_core.conversation.uuid7 import uuid7

    provided = (req.thread_id or "").strip()
    conv = rt.conversation_store.ensure_conversation(
        provided or str(uuid7()), user_id, req.module, title=req.title,
        retrieval_scope=req.retrieval_scope,
    )
    # 同步登记 memory 线程（sidebar 列表与检索范围持久化依赖）；失败不阻断。
    # memory 线程沿用客户端提供的 legacy id（供 PATCH/DELETE/GET 列表定位），
    # 缺省时才用 conversation UUID。
    memory_key = provided or conv["id"]
    try:
        rt.register_thread(
            memory_key, user_id, module=req.module, title=req.title or "",
            retrieval_scope=req.retrieval_scope,
        )
    except Exception:
        pass
    return {
        "thread_id": conv["id"],
        "module": conv.get("module", req.module),
        "title": conv.get("title"),
        "created_at": conv.get("created_at"),
    }


@router.get("/threads/{thread_id}/messages")
def list_messages(thread_id: str, current_user: CurrentUser,
                  rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> list[dict]:
    """返回会话全部消息（按 turn sequence_no + created_at 排序），支持 UUID 或 legacy id。"""
    user_id = current_user["id"]
    rt._ensure_heavy()
    try:
        msgs = rt.conversation_store.list_messages(thread_id, user_id)
    except OwnershipError as e:
        raise HTTPException(status_code=404, detail="会话不存在或已被删除") from e
    return [
        {
            "id": m["id"],
            "turn_id": m["turn_id"],
            "role": m["role"],
            "content": m["content"],
            "status": m["status"],
            "run_id": m.get("run_id"),
            "regenerated_from_message_id": m.get("regenerated_from_message_id"),
            "created_at": m.get("created_at"),
            "completed_at": m.get("completed_at"),
            "metadata": m.get("metadata"),
        }
        for m in msgs
    ]


@router.post("/messages/{message_id}/regenerate")
def regenerate_message(
    message_id: str,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> StreamingResponse:
    """重新生成最后一条完整 assistant 消息（§34）：复用 turn，新建 run + 新 message。

    - 支持 ``Idempotency-Key: uuid`` 头（§38）：同 (user, key) 二次请求直接返回
      首次生成的 message 行（NDJSON done 事件），不重跑。
    - 成功为 NDJSON 流（stage → chunk×n → done 携带稳定 ID：turn 不变、
      新 run_id/message_id）；校验失败 404/409 用 JSON 响应。
    """
    user_id = current_user["id"]
    rt._ensure_heavy()

    # ── 幂等头：命中返回首次结果（不重跑）──
    if idempotency_key:
        existing_id = rt.conversation_store.get_regeneration(user_id, idempotency_key)
        if existing_id:
            existing = rt.conversation_store.get_message(user_id, existing_id)

            def replay() -> Generator[str, None, None]:
                if existing is not None:
                    yield done_event(
                        existing.get("content", "") or "",
                        thread_id=existing.get("thread_id", ""),
                        turn_id=existing.get("turn_id", ""),
                        message_id=existing.get("id", ""),
                        run_id=existing.get("run_id"),
                        status=existing.get("status"),
                        regenerated_from_message_id=existing.get("regenerated_from_message_id"),
                    )
                else:
                    yield error_event("幂等命中但消息已不存在，请重试")

            return StreamingResponse(
                replay(),
                media_type="application/x-ndjson",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

    # ── 前置校验：同步映射 404/409（JSON 响应）──
    try:
        rt.validate_regenerate(message_id, user_id)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail="消息不存在或不属于当前用户") from e
    except RegenerateConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    def gen() -> Generator[str, None, None]:
        result: dict = {"content": "", "turn": None}
        cancel = CancellationEvent()

        def run_fn(cb):
            nonlocal result
            res = rt.run_regenerate_stream(
                message_id, user_id, cb, cancel_check=cancel.check
            )
            result["content"] = (res.content if hasattr(res, "content") else res) or ""
            result["turn"] = getattr(res, "turn", None)

        failed = False
        try:
            yield stage_event("regenerate")
            content_parts: list[str] = []
            for line in stream_agent(run_fn, cancel=cancel):
                evt = json.loads(line)
                if evt["type"] == "error":
                    failed = True
                elif evt["type"] == "chunk":
                    content_parts.append(evt["text"])
                yield line
            if not failed:
                done_fields = turn_done_fields(result["turn"])
                if result["turn"] is not None:
                    done_fields["regenerated_from_message_id"] = message_id
                yield done_event(
                    result["content"] or "".join(content_parts),
                    **done_fields,
                )
        except Exception as e:
            yield error_event(f"生成失败：{e}")

    # 带幂等键：done 事件后登记（保证流中途失败不污名化该 key）
    if idempotency_key:
        def gen_with_idem() -> Generator[str, None, None]:
            done_message_id: str | None = None
            for line in gen():
                yield line
                try:
                    evt = json.loads(line)
                    if evt.get("type") == "done":
                        done_message_id = evt.get("message_id")
                except Exception:
                    pass
            if done_message_id:
                rt.conversation_store.create_regeneration(
                    user_id, idempotency_key, done_message_id
                )
        stream_gen = gen_with_idem()
    else:
        stream_gen = gen()

    return StreamingResponse(
        stream_gen,
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

