"""traces 路由：/api/runs（LangSmith 读取，AGENT_LANGSMITH_SPEC Part B）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime
from careercrew_core.tracing.langsmith import RunNotFoundError

router = APIRouter()


@router.get("/runs")
def runs(
    limit: int = Query(50, ge=1, le=200),
    user_id: str | None = Query(None),
    thread_id: str | None = Query(None),
    stage: str | None = Query(None),
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> dict:
    """列最近根 run（一次用户请求=一条根 run）。"""
    try:
        return {
            "runs": rt.list_runs(
                limit=limit, user_id=user_id, thread_id=thread_id, stage=stage
            )
        }
    except Exception as e:  # noqa: BLE001 - 读取侧失败统一 503 可读错误
        raise HTTPException(status_code=503, detail=f"追踪服务不可用: {e}") from e


@router.get("/runs/{run_id}")
def run_detail(run_id: str, rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> dict:
    """run 详情 + 展平子 run 时间线（输入输出预览已脱敏/截断）。"""
    try:
        return rt.get_run_detail(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail=f"run 不存在: {run_id}")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"追踪服务不可用: {e}") from e

