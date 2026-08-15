"""threads 路由：对话会话（conversation 表，Source of Truth）创建与消息恢复。

- POST /api/threads           新建会话（服务端生成 UUID；兼容旧 thread_id 形参）
- GET  /api/threads/{thread_id}/messages  按 turn sequence 返回全部消息（§37 状态恢复）

与 data.py 的 memory 线程（GET/PATCH/DELETE /api/threads，sidebar 列表）分工：
本路由负责 conversation 表（稳定 ID 的 Source of Truth）；创建时同时登记 memory
线程元数据（sidebar 可见），保持 episodic 双写与既有前端行为不变。
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from careercrew_api.auth.dependencies import CurrentUser
from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime, ResourceNotFoundError
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


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


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
        raise HTTPException(status_code=404, detail="thread not found") from e
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
        }
        for m in msgs
    ]
