"""chat 路由：M1 对话闭环（match 流式 + resume 流式）。

状态由 thread_id -> JobCycle 缓存承接：match 流结束 -> 前端展示结果 ->
用户选 JD -> resume 流。
"""
from __future__ import annotations

import json
from collections.abc import Generator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from careercrew_api.auth.dependencies import CurrentUser
from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime, RuntimeInitError
from careercrew_api.schemas import MatchRequest, ResumeRequest
from careercrew_api.sse import (
    CancellationEvent,
    done_event,
    error_event,
    stage_event,
    stream_agent,
    turn_done_fields,
)

router = APIRouter()


def _turn_done_fields(turn) -> dict:
    return turn_done_fields(turn)


def _ndjson_response(gen: Generator[str, None, None]) -> StreamingResponse:
    """统一 NDJSON 响应头。"""
    return StreamingResponse(
        gen,
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/match")
def match(
    req: MatchRequest,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> StreamingResponse:
    """阶段 match：JobMatcher 找匹配岗位，流式输出。"""

    def gen() -> Generator[str, None, None]:
        result: dict = {"content": "", "turn": None}
        cancel = CancellationEvent()

        def run_fn(cb):
            nonlocal result
            res = rt.run_match_stream(
                req.thread_id, current_user["id"], req.intent, cb,
                cancel_check=cancel.check,
            )
            result["content"] = (res.content if hasattr(res, "content") else res) or ""
            result["turn"] = getattr(res, "turn", None)

        try:
            yield stage_event("match")
            content_parts: list[str] = []
            for line in stream_agent(run_fn, cancel=cancel):
                evt = json.loads(line)
                if evt["type"] == "chunk":
                    content_parts.append(evt["text"])
                yield line
            # 最终内容以 agent 最后一轮回答为准（流式 chunk 可能含中间轮开头话）
            yield done_event(
                result["content"] or "".join(content_parts),
                **_turn_done_fields(result["turn"]),
            )
        except RuntimeInitError as e:
            yield error_event(str(e))
        except Exception as e:
            yield error_event(str(e))

    return _ndjson_response(gen())


@router.post("/resume")
def resume(
    req: ResumeRequest,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> StreamingResponse:
    """阶段 resume：ResumeAdvisor 按 JD 定制简历（带跨步骤历史），流式输出。"""

    def gen() -> Generator[str, None, None]:
        result: dict = {"content": "", "turn": None}
        cancel = CancellationEvent()

        def run_fn(cb):
            nonlocal result
            res = rt.run_resume_stream(
                req.thread_id, current_user["id"], req.jd_text, cb,
                cancel_check=cancel.check,
            )
            result["content"] = (res.content if hasattr(res, "content") else res) or ""
            result["turn"] = getattr(res, "turn", None)

        try:
            yield stage_event("resume")
            content_parts: list[str] = []
            for line in stream_agent(run_fn, cancel=cancel):
                evt = json.loads(line)
                if evt["type"] == "chunk":
                    content_parts.append(evt["text"])
                yield line
            # 最终内容以 agent 最后一轮回答为准
            yield done_event(
                result["content"] or "".join(content_parts),
                **_turn_done_fields(result["turn"]),
            )
        except RuntimeInitError as e:
            yield error_event(str(e))
        except Exception as e:
            yield error_event(str(e))

    return _ndjson_response(gen())


@router.post("/plan")
def plan(
    req: MatchRequest,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> StreamingResponse:
    """求职对话：职业规划师主理（一站式画像/规划/匹配/简历/薪资），流式输出。"""

    def gen() -> Generator[str, None, None]:
        result: dict = {"content": "", "turn": None}
        cancel = CancellationEvent()

        def run_fn(cb):
            nonlocal result
            res = rt.run_planner_chat_stream(
                req.thread_id, current_user["id"], req.intent, cb,
                cancel_check=cancel.check,
            )
            result["content"] = (res.content if hasattr(res, "content") else res) or ""
            result["turn"] = getattr(res, "turn", None)

        try:
            yield stage_event("planning")
            content_parts: list[str] = []
            for line in stream_agent(run_fn, cancel=cancel):
                evt = json.loads(line)
                if evt["type"] == "chunk":
                    content_parts.append(evt["text"])
                yield line
            # 最终内容以 agent 最后一轮回答为准（流式 chunk 可能含中间轮开头话）
            yield done_event(
                result["content"] or "".join(content_parts),
                **_turn_done_fields(result["turn"]),
            )
        except RuntimeInitError as e:
            yield error_event(str(e))
        except Exception as e:
            yield error_event(str(e))

    return _ndjson_response(gen())
