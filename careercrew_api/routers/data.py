"""data 路由：health / config / profile / threads / memory / settings / policy。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime, RuntimeInitError
from careercrew_api.schemas import HealthResponse

router = APIRouter()


class ProfileUpdateRequest(BaseModel):
    fields: dict[str, Any]


class ThreadCreateRequest(BaseModel):
    thread_id: str
    module: str = "chat"
    title: str = ""


class ThreadPatchRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    module: str | None = None


class MemoryPolicyRequest(BaseModel):
    enabled: bool | None = None
    generate: bool | None = None
    use: bool | None = None


class MemorySettingsRequest(BaseModel):
    enabled: bool | None = None
    generate: bool | None = None
    use: bool | None = None


@router.get("/health", response_model=HealthResponse)
def health(rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> HealthResponse:
    """健康检查：读 settings 不触发重初始化。"""
    info = rt.health_info()
    return HealthResponse(
        status=info.get("status", "ok"),
        model=info.get("model", ""),
        embedding=info.get("embedding", ""),
        vector_store=info.get("vector_store", ""),
        ready=info.get("ready", False),
        error=info.get("error"),
    )


@router.get("/config")
def config() -> dict:
    """读 settings 汇总（llm / embedding / rerank / vector_store / rag）。"""
    from careercrew_core.state.settings import load_settings

    s = load_settings()
    return {
        "llm": s.llm.model, "embedding": s.embedding.provider,
        "rerank": s.rerank.backend, "vector_store": s.vector_store.backend,
        "rag": s.rag.retrieval.mode,
    }


@router.get("/profile")
def profile(user_id: str = Query("u_001"),
            rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """从语义事实聚合 UserModel 投影（走 runtime 记忆库，生产为 Postgres）。"""
    rt._ensure_heavy()
    from careercrew_core.memory.semantic import SemanticFactStore

    store = SemanticFactStore(rt.memory_db, user_id)
    return store.load(user_id).model_dump()


@router.put("/profile")
def update_profile(req: ProfileUpdateRequest, user_id: str = Query("u_001"),
                   rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """更新用户画像字段（白名单约束，写入语义事实）。"""
    rt._ensure_heavy()
    try:
        model = rt.fact_store.update(user_id, req.fields, source="api")
        return model.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/threads")
def threads(module: str | None = Query(None), user_id: str = Query("u_001"),
            rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> list[dict]:
    """列出用户的所有对话线程（Postgres threads 表）。"""
    return rt.get_threads(user_id, module=module)


@router.post("/threads")
def create_thread(req: ThreadCreateRequest, user_id: str = Query("u_001"),
                  rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """登记新会话线程。"""
    return rt.register_thread(req.thread_id, user_id, module=req.module, title=req.title)


@router.patch("/threads/{thread_id}")
def patch_thread(thread_id: str, req: ThreadPatchRequest, user_id: str = Query("u_001"),
                 rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """更新线程标题 / 置顶 / 模块。"""
    return rt.touch_thread(
        thread_id, user_id,
        title=req.title, pinned=req.pinned,
        module=req.module or "chat",
    )


@router.delete("/threads/{thread_id}")
def delete_thread(thread_id: str, user_id: str = Query("u_001"),
                  rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """删除指定对话线程（情景事件 + 线程元数据）。"""
    return rt.delete_thread(thread_id, user_id)


@router.get("/memory")
def memory(user_id: str = Query("u_001"), thread_id: str | None = Query(None),
           type: str = Query(""), rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> list[dict]:
    """读取语义事实 + 情景事件（可过滤）。"""
    return rt.memory_list(user_id, thread_id=thread_id, type=type)


@router.delete("/memory")
def delete_memory(kind: str = Query(""), name: str | None = Query(None),
                  entry_id: str | None = Query(None), thread_id: str | None = Query(None),
                  type: str = Query(""), user_id: str = Query("u_001"),
                  rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """删除语义事实（kind=fact&name）或情景事件（kind=event&entry_id）。"""
    removed = rt.memory_delete(
        user_id, kind=kind, name=name, entry_id=entry_id, thread_id=thread_id, type=type
    )
    return {"deleted": removed, "removed": removed}


@router.get("/memory/policy")
def memory_policy(user_id: str = Query("u_001"),
                  rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """用户级记忆策略（enabled/generate/use + 生效值）。"""
    return rt.memory_policy_get(user_id)


@router.put("/memory/policy")
def update_memory_policy(req: MemoryPolicyRequest, user_id: str = Query("u_001"),
                         rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """更新用户级记忆策略。"""
    return rt.memory_policy_set(
        user_id, enabled=req.enabled, generate=req.generate, use=req.use
    )


@router.get("/settings/memory")
def memory_settings(rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """全局记忆设置（特性开关 + 全局策略）。"""
    return rt.memory_settings_get()


@router.put("/settings/memory")
def update_memory_settings(req: MemorySettingsRequest,
                           rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """更新全局记忆开关（持久化到 memory_global_policy）。"""
    return rt.memory_settings_set(
        enabled=req.enabled, generate=req.generate, use=req.use
    )


@router.post("/memory/consolidate")
def consolidate(user_id: str = Query("u_001"), force: bool = Query(False),
                rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """手动触发后台 consolidation（测试/运维用）。"""
    return rt.memory_consolidate(user_id, force=force)
