"""data 路由：health / config / profile / memory / traces / threads。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime, RuntimeInitError
from careercrew_api.schemas import HealthResponse

router = APIRouter()


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
    """复用 dashboard get_settings_summary()。"""
    from careercrew_ui.dashboard.data import get_settings_summary

    return get_settings_summary()


@router.get("/profile")
def profile(user_id: str = Query("u_001")) -> dict:
    from careercrew_ui.dashboard.data import get_user_model

    return get_user_model(user_id)


@router.put("/profile")
def update_profile(fields: dict, user_id: str = Query("u_001")) -> dict:
    """更新用户画像字段（白名单约束）。"""
    from careercrew_core.memory.user_model import UserModelStore
    from careercrew_core.state.settings import load_settings

    settings = load_settings()
    store = UserModelStore(settings.memory.user_model.path)
    model = store.update(user_id, fields)
    return model.model_dump()


@router.get("/threads")
def threads(user_id: str = Query("u_001"), rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> list[dict]:
    """列出用户的所有对话线程（每个 thread = 一个对话 = 一个情景记忆文件）。"""
    return rt.get_threads(user_id)


@router.delete("/threads/{thread_id}")
def delete_thread(thread_id: str, user_id: str = Query("u_001")) -> dict:
    """删除指定对话线程的记忆文件。"""
    from pathlib import Path
    from careercrew_core.state.settings import load_settings

    settings = load_settings()
    path = Path(settings.memory.episodic.transcript_dir) / user_id / f"{thread_id}.jsonl"
    if path.exists():
        path.unlink()
        return {"deleted": True, "thread_id": thread_id}
    return {"deleted": False, "thread_id": thread_id}


@router.get("/memory")
def memory(user_id: str = Query("u_001"), thread_id: str | None = Query(None), type: str = Query("")) -> list[dict]:
    """读取情景记忆条目。

    传 thread_id：只读该线程；不传：读取该用户所有线程的记忆（合并按时间排序）。
    """
    from pathlib import Path

    from careercrew_core.memory.episodic import EpisodicMemory
    from careercrew_core.state.settings import load_settings

    settings = load_settings()
    transcript_dir = Path(settings.memory.episodic.transcript_dir) / user_id

    if thread_id:
        files = [transcript_dir / f"{thread_id}.jsonl"]
    else:
        # 所有线程合并
        files = sorted(transcript_dir.glob("*.jsonl"))

    entries = []
    for f in files:
        if f.exists():
            entries.extend(e.model_dump() for e in EpisodicMemory(f)._read_all())
    entries.sort(key=lambda e: e.get("ts", ""))

    if type:
        entries = [e for e in entries if e.get("type") == type]
    return entries
