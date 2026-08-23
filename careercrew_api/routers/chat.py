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
from careercrew_api.limits import user_stream_slot
from careercrew_api.request_helpers import (
    ndjson_response as _ndjson_response,
)
from careercrew_api.request_helpers import (
    resolve_attachments_or_422 as _resolve_attachments,
)
from careercrew_api.request_helpers import (
    resolve_mentions_or_422 as _resolve_mentions,
)
from careercrew_api.runtime import CareerCrewRuntime
from careercrew_api.schemas import MatchRequest, ResumeRequest
from careercrew_api.sse import (
    CancellationEvent,
    done_event,
    error_event,
    friendly_error,
    stage_event,
    stream_agent,
    turn_done_fields,
)

router = APIRouter()


@router.post("/match")
def match(
    req: MatchRequest,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
    _slot: None = Depends(user_stream_slot),
) -> StreamingResponse:
    """阶段 match：JobMatcher 找匹配岗位，流式输出。"""

    mentions = _resolve_mentions(rt, current_user["id"], req.mentions)
    attachment_blocks = _resolve_attachments(rt, current_user["id"], req.attachments)

    def gen() -> Generator[str, None, None]:
        result: dict = {"content": "", "turn": None}
        cancel = CancellationEvent()

        def run_fn(cb):
            nonlocal result
            res = rt.run_match_stream(
                req.thread_id, current_user["id"], req.intent, cb,
                **({"mentions": mentions} if mentions else {}),
                **({"attachments": attachment_blocks} if attachment_blocks else {}),
                cancel_check=cancel.check,
                tools=req.tools,
            )
            result["content"] = (res.content if hasattr(res, "content") else res) or ""
            result["turn"] = getattr(res, "turn", None)

        failed = False
        try:
            yield stage_event("match")
            content_parts: list[str] = []
            for line in stream_agent(run_fn, cancel=cancel):
                evt = json.loads(line)
                if evt["type"] == "error":
                    failed = True
                elif evt["type"] == "chunk":
                    content_parts.append(evt["text"])
                yield line
            # 最终内容以 agent 最后一轮回答为准（流式 chunk 可能含中间轮开头话）
            # 出错时不补发 done，避免前端错误提示被空回答覆盖
            if not failed:
                yield done_event(
                    result["content"] or "".join(content_parts),
                    **turn_done_fields(result["turn"]),
                )
        except Exception as e:
            yield error_event(friendly_error(e))

    return _ndjson_response(gen())


@router.post("/resume")
def resume(
    req: ResumeRequest,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
    _slot: None = Depends(user_stream_slot),
) -> StreamingResponse:
    """阶段 resume：ResumeAdvisor 按 JD 定制简历（带跨步骤历史），流式输出。"""

    mentions = _resolve_mentions(rt, current_user["id"], req.mentions)
    attachment_blocks = _resolve_attachments(rt, current_user["id"], req.attachments)

    def gen() -> Generator[str, None, None]:
        result: dict = {"content": "", "turn": None}
        cancel = CancellationEvent()

        def run_fn(cb):
            nonlocal result
            res = rt.run_resume_stream(
                req.thread_id, current_user["id"], req.jd_text, cb,
                **({"mentions": mentions} if mentions else {}),
                **({"attachments": attachment_blocks} if attachment_blocks else {}),
                cancel_check=cancel.check,
                tools=req.tools,
            )
            result["content"] = (res.content if hasattr(res, "content") else res) or ""
            result["turn"] = getattr(res, "turn", None)

        failed = False
        try:
            yield stage_event("resume")
            content_parts: list[str] = []
            for line in stream_agent(run_fn, cancel=cancel):
                evt = json.loads(line)
                if evt["type"] == "error":
                    failed = True
                elif evt["type"] == "chunk":
                    content_parts.append(evt["text"])
                yield line
            # 最终内容以 agent 最后一轮回答为准
            if not failed:
                yield done_event(
                    result["content"] or "".join(content_parts),
                    **turn_done_fields(result["turn"]),
                )
        except Exception as e:
            yield error_event(friendly_error(e))

    return _ndjson_response(gen())


@router.post("/plan")
def plan(
    req: MatchRequest,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
    _slot: None = Depends(user_stream_slot),
) -> StreamingResponse:
    """求职对话：职业规划师主理（一站式画像/规划/匹配/简历/薪资），流式输出。"""

    mentions = _resolve_mentions(rt, current_user["id"], req.mentions)
    attachment_blocks = _resolve_attachments(rt, current_user["id"], req.attachments)

    def gen() -> Generator[str, None, None]:
        result: dict = {"content": "", "turn": None}
        cancel = CancellationEvent()

        def run_fn(cb):
            nonlocal result
            res = rt.run_planner_chat_stream(
                req.thread_id, current_user["id"], req.intent, cb,
                **({"mentions": mentions} if mentions else {}),
                **({"attachments": attachment_blocks} if attachment_blocks else {}),
                cancel_check=cancel.check,
                tools=req.tools,
            )
            result["content"] = (res.content if hasattr(res, "content") else res) or ""
            result["turn"] = getattr(res, "turn", None)

        failed = False
        try:
            yield stage_event("planning")
            content_parts: list[str] = []
            for line in stream_agent(run_fn, cancel=cancel):
                evt = json.loads(line)
                if evt["type"] == "error":
                    failed = True
                elif evt["type"] == "chunk":
                    content_parts.append(evt["text"])
                yield line
            # 最终内容以 agent 最后一轮回答为准（流式 chunk 可能含中间轮开头话）
            if not failed:
                yield done_event(
                    result["content"] or "".join(content_parts),
                    **turn_done_fields(result["turn"]),
                )
        except Exception as e:
            yield error_event(friendly_error(e))

    return _ndjson_response(gen())
