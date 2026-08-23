"""data 路由：health / config / profile / threads / memory / settings / policy。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator

from careercrew_api.auth.dependencies import AdminUser, CurrentUser
from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime, ResourceNotFoundError
from careercrew_api.schemas import HealthResponse
from careercrew_core.memory.semantic import SemanticFactStore

router = APIRouter()


class ProfileUpdateRequest(BaseModel):
    fields: dict[str, Any]


class RetrievalScopeRequest(BaseModel):
    """会话检索范围（两个正交维度）：

    type: 可见范围（all=全部 / public=公共库 / private=个人库）
    category_id: 可选内容分类（resume/knowledge/interview/job）
    兼容旧格式 {"type": "category", "category_id": ...}，归一化为 type=all + category_id。
    """

    type: str = "all"
    category_id: str | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.type == "category":  # 旧格式归一化
            if not self.category_id or not self.category_id.strip():
                raise ValueError("type=category 时必须提供 category_id")
            self.type = "all"
            return self
        if self.type not in ("all", "public", "private"):
            raise ValueError("type 必须为 all / public / private")
        if not self.category_id or not self.category_id.strip():
            self.category_id = None
        return self


class ThreadPatchRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    module: str | None = None
    retrieval_scope: RetrievalScopeRequest | None = None


class MemoryPolicyRequest(BaseModel):
    enabled: bool | None = None
    generate: bool | None = None
    use: bool | None = None


class MemorySettingsRequest(BaseModel):
    enabled: bool | None = None
    generate: bool | None = None
    use: bool | None = None


@router.get("/health", response_model=HealthResponse)
def health(current_user: CurrentUser,
           rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> HealthResponse:
    """健康检查：读 settings 不触发重初始化。

    返回模型名 / embedding / 向量库后端等部署细节，须登录后访问
    （无鉴权探针走公开的 GET /healthz 与 /readyz）。
    """
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
def config(_current_user: CurrentUser) -> dict:
    """读 settings 汇总（llm / embedding / rerank / vector_store / rag）。"""
    from careercrew_core.state.settings import load_settings

    s = load_settings()
    return {
        "llm": s.llm.model, "embedding": s.embedding.provider,
        "rerank": s.rerank.backend, "vector_store": s.vector_store.backend,
        "rag": s.rag.retrieval.mode,
    }


@router.get("/profile")
def profile(current_user: CurrentUser,
            rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """从语义事实聚合 UserModel 投影（走 runtime 记忆库，生产为 Postgres）。"""
    rt._ensure_heavy()
    from careercrew_core.memory.semantic import SemanticFactStore

    user_id = current_user["id"]
    store = SemanticFactStore(rt.memory_db, user_id)
    return store.load().model_dump()


@router.put("/profile")
def update_profile(req: ProfileUpdateRequest, current_user: CurrentUser,
                   rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """更新用户画像字段（白名单约束，写入语义事实）。"""
    rt._ensure_heavy()
    try:
        store = SemanticFactStore(rt.memory_db, current_user["id"])
        model = store.update(current_user["id"], req.fields, source="api")
        return model.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/threads")
def threads(current_user: CurrentUser, module: str | None = Query(None),
            rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> list[dict]:
    """列出用户的所有对话线程（Postgres threads 表）。"""
    return rt.get_threads(current_user["id"], module=module)


@router.patch("/threads/{thread_id}")
def patch_thread(thread_id: str, req: ThreadPatchRequest, current_user: CurrentUser,
                 rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """更新线程标题 / 置顶 / 模块 / 检索范围。"""
    try:
        return rt.touch_thread(
            thread_id, current_user["id"],
            title=req.title, pinned=req.pinned,
            module=req.module,
            retrieval_scope=req.retrieval_scope.model_dump(exclude_none=True) if req.retrieval_scope else None,
        )
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail="会话不存在或已被删除") from e


@router.delete("/threads/{thread_id}")
def delete_thread(thread_id: str, current_user: CurrentUser,
                  rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """删除指定对话线程（情景事件 + 线程元数据）。"""
    try:
        return rt.delete_thread(thread_id, current_user["id"])
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail="会话不存在或已被删除") from e


@router.get("/memory")
def memory(current_user: CurrentUser, thread_id: str | None = Query(None),
           type: str = Query(""), rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> list[dict]:
    """读取语义事实 + 情景事件（可过滤）。"""
    return rt.memory_list(current_user["id"], thread_id=thread_id, type=type)


@router.delete("/memory")
def delete_memory(current_user: CurrentUser, kind: str = Query(""), name: str | None = Query(None),
                  entry_id: str | None = Query(None), thread_id: str | None = Query(None),
                  type: str = Query(""),
                  rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """删除语义事实（kind=fact&name）或情景事件（kind=event&entry_id）。"""
    removed = rt.memory_delete(
        current_user["id"], kind=kind, name=name, entry_id=entry_id,
        thread_id=thread_id, type=type,
    )
    return {"deleted": removed, "removed": removed}


@router.get("/memory/policy")
def memory_policy(current_user: CurrentUser,
                  rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """用户级记忆策略（enabled/generate/use + 生效值）。"""
    return rt.memory_policy_get(current_user["id"])


@router.put("/memory/policy")
def update_memory_policy(req: MemoryPolicyRequest, current_user: CurrentUser,
                         rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """更新用户级记忆策略。"""
    return rt.memory_policy_set(
        current_user["id"], enabled=req.enabled, generate=req.generate, use=req.use
    )


@router.get("/settings/memory")
def memory_settings(
    _current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    """全局记忆设置（特性开关 + 全局策略）。"""
    return rt.memory_settings_get()


@router.put("/settings/memory")
def update_memory_settings(req: MemorySettingsRequest,
                           _admin: AdminUser,
                           rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """更新全局记忆开关（持久化到 memory_global_policy）。"""
    return rt.memory_settings_set(
        enabled=req.enabled, generate=req.generate, use=req.use
    )


@router.post("/memory/consolidate")
def consolidate(current_user: CurrentUser, force: bool = Query(False),
                rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """手动触发后台 consolidation（测试/运维用）。"""
    return rt.memory_consolidate(current_user["id"], force=force)
