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

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, field_validator

from careercrew_api.auth.dependencies import CurrentUser
from careercrew_api.deps import get_runtime_dep
from careercrew_api.routers.data import RetrievalScopeRequest
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


def _replay_done_event(rt: CareerCrewRuntime, msg: dict) -> str:
    """幂等 replay 的 done 事件：与正常路径同字段集（§9）。

    除 message 行自带字段外，补 model / prompt_version / agent_version（§9 版本字段），
    从该 message 关联的 run 行读取；无 run 行时回退 "unversioned"/空。
    """
    run = None
    if msg.get("run_id"):
        run = rt.conversation_store.get_run(msg["user_id"], msg["run_id"])
    run = run or {}
    return done_event(
        msg.get("content", "") or "",
        thread_id=msg.get("thread_id", ""),
        turn_id=msg.get("turn_id", ""),
        message_id=msg.get("id", ""),
        run_id=msg.get("run_id"),
        status=msg.get("status", "completed"),
        regenerated_from_message_id=msg.get("regenerated_from_message_id"),
        model=run.get("model") or "",
        prompt_version=run.get("prompt_version") or "unversioned",
        agent_version=run.get("agent_version") or "unversioned",
    )


def _release_idem(rt: CareerCrewRuntime, user_id: str, key: str | None, reserved: bool) -> None:
    """前置校验失败时释放已预留的幂等键（不保留无效 key）。"""
    if reserved and key:
        try:
            rt.conversation_store.release_regeneration(user_id, key)
        except Exception:
            pass


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


class ThreadRenameRequest(BaseModel):
    """PATCH /threads/{thread_id}：兼容 legacy data.py 的 title/pinned/module/retrieval_scope。

    title 额外同步 conversation 表（§13.1）；其余字段仅更新 legacy thread_store
    （侧边栏元数据），保持既有行为不变。
    """

    title: str | None = None
    pinned: bool | None = None
    module: str | None = None
    retrieval_scope: "RetrievalScopeRequest | None" = None


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


@router.patch("/threads/{thread_id}")
def rename_thread(thread_id: str, req: ThreadRenameRequest, current_user: CurrentUser,
                  rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """更新会话元数据（§13.1 + legacy 兼容）。

    保持 legacy data.py PATCH 语义（title/pinned/module/retrieval_scope 走 thread_store）；
    仅当 title 变化时额外同步 conversation 表（Source of Truth）。凡 body 全空或
    跨用户/不存在 → 404（除非法范围仍按 legacy 422）。
    """
    user_id = current_user["id"]
    rt._ensure_heavy()

    # legacy 语义：先经由 thread_store 更新（含 pinned/module/retrieval_scope 归一化）
    try:
        scope = (
            req.retrieval_scope.model_dump(exclude_none=True)
            if req.retrieval_scope is not None
            else None
        )
        legacy = rt.touch_thread(
            thread_id, user_id,
            title=req.title, pinned=req.pinned, module=req.module,
            retrieval_scope=scope,
        )
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail="会话不存在或已被删除") from e

    # §13.1：title 同步 conversation 表（有 conversation 行才更新；仅 legacy-only
    # 线程静默跳过，其余异常上抛——不静默接受 title 分歧）。
    if req.title is not None and req.title.strip():
        try:
            rt.conversation_store.rename_title(thread_id, user_id, req.title.strip()[:50])
        except OwnershipError:
            pass  # 无 conversation 行（纯 legacy 线程）：只更新 thread_store，符合既有行为
        # 其余异常（DB 等）不吞：直接上抛，避免 title 分歧静默存在。

    return legacy


@router.delete("/threads/{thread_id}")
def delete_conversation(thread_id: str, current_user: CurrentUser,
                        rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """删除会话（§13.5）：conversation 表全删 + legacy thread_store/情景事件一并删除。

    顺序：先删 legacy thread_store（纯 legacy 线程 ≥ T1.3 无 conversation 行也要能删），
    失败即中止（无部分删除）、错误上抛；成功后再删 conversation 行。仅当 conversation
    删成功（或本就是纯 legacy 线程）才返回成功；两者都不存在（或跨用户）→ 404。
    """
    user_id = current_user["id"]
    rt._ensure_heavy()

    # 1) 先删 legacy thread_store（sidebar 元数据 + 情景事件）；失败即中止、上抛，
    #    避免 conversation 先删而后 legacy 清理失败造成部分删除。
    try:
        legacy = rt.delete_thread(thread_id, user_id)
    except ResourceNotFoundError as e:
        # 无 legacy 元数据：若存在 conversation 则继续删 conversation，否则整体 404。
        conv_exists = True
        try:
            rt.conversation_store.delete_conversation(thread_id, user_id)
        except OwnershipError:
            raise HTTPException(status_code=404, detail="会话不存在或已被删除") from e
        return {"deleted": conv_exists, "thread_id": thread_id}

    # 2) legacy 已删；再删 conversation 行（无 conversation 行 → 纯 legacy 线程，已删成）。
    try:
        rt.conversation_store.delete_conversation(thread_id, user_id)
    except OwnershipError:
        pass  # 纯 legacy 线程（无 conversation 行）：legacy 路径已删除成功
    return {"deleted": legacy.get("deleted", False), "thread_id": thread_id}


@router.post("/threads/{thread_id}/clear")
def clear_conversation(thread_id: str, current_user: CurrentUser,
                       rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """清空会话消息（§13.4）：保留 conversation/title/retrieval_scope，删除全部消息与 turn。

    同时删除该 thread 的 legacy episodic 情景事件（episodic_events）——否则
    restoreHistory 在 messages 端点为空时回退记忆，会把清掉的旧消息捞回来
    （「清空后切走再切回，旧消息复活」）。episodic 清理失败不阻断清空主流程。
    """
    user_id = current_user["id"]
    rt._ensure_heavy()
    try:
        removed = rt.conversation_store.clear_conversation(thread_id, user_id)
    except OwnershipError as e:
        raise HTTPException(status_code=404, detail="会话不存在或已被删除") from e
    episodic_removed = 0
    try:
        episodic_removed = rt.memory_db.delete_episodic(user_id, thread_id=thread_id)
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "clear_conversation: episodic cleanup failed for %s", thread_id
        )
    return {
        "cleared": True, "thread_id": thread_id, "removed_turns": removed,
        "removed_episodic": episodic_removed,
    }


@router.get("/threads/{thread_id}/export")
def export_conversation(
    thread_id: str,
    current_user: CurrentUser,
    format: str = Query(default="md", alias="format"),
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
):
    """导出会话（§13.2/§13.3）：format=md|json。

    数据源为 conversation 表（messages + agent_runs）。无 conversation 行的旧线程
    （仅 legacy thread_store 元数据）→ 404（决策：不做 episodic 回退，见报告）。
    """
    from careercrew_core.conversation.export import build_json_text, build_markdown

    user_id = current_user["id"]
    rt._ensure_heavy()
    if format not in ("md", "json"):
        raise HTTPException(status_code=400, detail="format 必须为 md 或 json")

    try:
        conv = rt.conversation_store.get_conversation(thread_id, user_id)
    except OwnershipError as e:
        raise HTTPException(status_code=404, detail="会话不存在或已被删除") from e
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在或已被删除")

    msgs = rt.conversation_store.list_messages(thread_id, user_id)
    runs = rt.conversation_store.list_runs(thread_id, user_id)

    if format == "md":
        content = build_markdown(conv, msgs)
        return PlainTextResponse(content, media_type="text/markdown; charset=utf-8")
    content = build_json_text(conv, msgs, runs)
    return PlainTextResponse(content, media_type="application/json; charset=utf-8")


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

    # ── 幂等头：上游原子预留，命中返回首次结果（不重跑）──
    # 预留必须先于 dispatch：同 (user, key) 并发请求只有一个能成功预留，
    # 其余拿到既有 message_id 走 replay，杜绝双跑。
    idem_reserved = False
    if idempotency_key:
        state, existing_id = rt.conversation_store.reserve_regeneration(
            user_id, idempotency_key
        )
        if state == "exists":
            if existing_id is None:
                # 首个同 key 请求仍在进行中（message_id 尚未回填）→ 拒绝，杜绝双跑。
                raise HTTPException(
                    status_code=409, detail="该幂等键的重新生成正在处理中"
                )
            # 已存在且完成：replay（stream 首次生成的 message 行，§9 字段完整）。
            existing = rt.conversation_store.get_message(user_id, existing_id)

            def replay() -> Generator[str, None, None]:
                if existing is not None:
                    yield _replay_done_event(rt, existing)
                else:
                    yield error_event("幂等命中但消息已不存在，请重试")

            return StreamingResponse(
                replay(),
                media_type="application/x-ndjson",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        # 本次成功预留，后续完成后回填。
        idem_reserved = True

    # ── 前置校验：同步映射 404/409（JSON 响应）──
    try:
        rt.validate_regenerate(message_id, user_id)
    except ResourceNotFoundError as e:
        _release_idem(rt, user_id, idempotency_key, idem_reserved)
        raise HTTPException(status_code=404, detail="消息不存在或不属于当前用户") from e
    except RegenerateConflictError as e:
        _release_idem(rt, user_id, idempotency_key, idem_reserved)
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
        done_message_id: str | None = None
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
                done_message_id = done_fields.get("message_id")
                yield done_event(
                    result["content"] or "".join(content_parts),
                    **done_fields,
                )
        except Exception as e:
            failed = True
            yield error_event(f"生成失败：{e}")
        finally:
            # 预留（上游）完成后回填真实 message_id；流中途失败释放预留，不污名化 key。
            if idem_reserved:
                if done_message_id:
                    rt.conversation_store.complete_regeneration(
                        user_id, idempotency_key, done_message_id
                    )
                else:
                    rt.conversation_store.release_regeneration(user_id, idempotency_key)

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

