"""consult 路由：多 agent 并行会诊 + 综合。

事件流：{stage:consult} -> {agent_start} -> {chunk,agent}×n -> {agent_end}
       -> {stage:synthesis} -> synthesis chunk -> {done, opinions, synthesis}
"""
from __future__ import annotations

import json
import queue
import re
import threading
from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from careercrew_api.attachment_context import AttachmentRejected, build_user_message
from careercrew_api.auth.dependencies import CurrentUser
from careercrew_api.deps import get_runtime_dep
from careercrew_api.limits import user_stream_slot
from careercrew_api.mentions import MentionRejected
from careercrew_api.runtime import CareerCrewRuntime, RuntimeInitError
from careercrew_api.schemas import ConsultRequest
from careercrew_api.sse import (
    STREAM_IDLE_TIMEOUT_SECONDS,
    CancellationEvent,
    StreamCancelled,
    friendly_error,
    put_guaranteed,
    turn_done_fields,
)
from careercrew_core.tracing.langsmith import attach_run_metadata, traced_call

router = APIRouter()

_SENTINEL = object()


def _ndjson_line(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False) + "\n"


def _chunk_text(text: str) -> list[str]:
    """按标点/长度拆分最终答案，模拟流式输出。"""
    parts = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in "。\n！？!?" or len(buf) >= 20:
            parts.append(buf)
            buf = ""
    if buf:
        parts.append(buf)
    return parts


def _profile_from_model(model) -> dict[str, str]:
    """把 UserModel 画像投影成会诊字段（与 USER_INPUT_FIELDS 对齐），空值省略。

    current_position 持久化在画像中（Task 4），缺失时由询问兜底。
    """
    p = model.profile
    prefs = model.preferences
    out: dict[str, str] = {}
    if p.current_position:
        out["current_position"] = p.current_position
    if p.experience_years:
        out["experience_years"] = str(p.experience_years)
    if p.skills:
        out["skills"] = "、".join(p.skills)
    if p.direction:
        out["target_direction"] = p.direction
    if prefs.city:
        out["city"] = "、".join(prefs.city)
    if prefs.salary_min or prefs.salary_max:
        out["salary"] = f"{prefs.salary_min or '?'}-{prefs.salary_max or '?'}K"
    if model.target_companies:
        out["target_companies"] = "、".join(model.target_companies)
    return out


# 会诊资料填写字段 -> 画像白名单字段（只有白名单键会被持久化）
_FIELD_MAP = {
    "current_position": "profile.current_position",
    "experience_years": "profile.experience_years",
    "skills": "profile.skills",
    "target_direction": "profile.direction",
    "city": "preferences.city",
}


def _persist_form_profile(rt, user_id: str, profile: dict[str, str]) -> None:
    mapped: dict[str, object] = {}
    for k, key in _FIELD_MAP.items():
        v = profile.get(k)
        if v is None or not str(v).strip():
            continue
        s = str(v).strip()
        if key == "profile.skills":
            mapped[key] = [p.strip() for p in re.split(r"[、,，/]", s) if p.strip()]
        elif key == "preferences.city":
            mapped[key] = [p.strip() for p in re.split(r"[、,，/]", s) if p.strip()]
        elif key == "profile.experience_years":
            try:
                mapped[key] = int(s)
            except ValueError:
                continue  # 无法转 int：跳过该键，不写畸变值
        else:
            mapped[key] = s
    if "current_position" in profile and not str(profile["current_position"]).strip():
        mapped["profile.current_position"] = ""
    if mapped:
        try:
            from careercrew_core.memory.semantic import SemanticFactStore

            store = SemanticFactStore(rt.memory_db, user_id)
            store.update(user_id, mapped, source="consult_form")
        except Exception:
            import logging
            logging.getLogger(__name__).exception("persist consult profile failed")


@router.post("")
def consult(
    req: ConsultRequest,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
    _slot: None = Depends(user_stream_slot),
) -> StreamingResponse:
    """会诊总调度官：自动编排顾问 -> 多轮并行调度 -> 最终答案。"""

    # T3.4 §15.2：mentions 服务端二次校验（拒绝越权引用 → 422）。
    mentions: list[dict] = []
    if req.mentions:
        try:
            mentions = rt.resolve_mentions(
                current_user["id"], [m.model_dump() for m in req.mentions]
            )
        except MentionRejected as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        except RuntimeInitError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e

    # T3.2：附件服务端校验所有权 + 读取内容（文本块）；整体拒绝 → 422。
    try:
        attachment_blocks = rt.resolve_attachment_blocks(
            current_user["id"], [a.model_dump() for a in req.attachments]
        )
    except AttachmentRejected as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except RuntimeInitError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    def gen() -> Generator[str, None, None]:
        q: queue.Queue = queue.Queue(maxsize=512)
        err: dict[str, BaseException] = {}
        cancel = CancellationEvent()
        dropped = [0]

        def _safe_emit(item: dict) -> None:
            """取消感知 + 背压安全的事件投递：chunk 类可丢弃，终态事件保证投递。"""
            cancel.check()
            try:
                q.put_nowait(item)
            except queue.Full:
                if item.get("type") in ("done", "input_request", "error"):
                    put_guaranteed(q, item, cancel)
                else:
                    dropped[0] += 1

        def _worker_impl():
            user_id = current_user["id"]
            attach_run_metadata(user_id=user_id, thread_id=req.thread_id, stage="consult")
            from careercrew_api.runtime import _capture_langsmith_run_id

            ls_run_id = _capture_langsmith_run_id()
            # T3.5：会诊各顾问按各自 kind 构造工具；effective 由 consult 模块 allowlist
            # 计算后下发给 new_consult_agent，逐顾问再由 `_make_tools(kind, allowed=…)`
            # 裁剪到其实际注册集合。
            effective = rt.compute_effective_tools("consult", req.tools)
            hitl = rt._hitl_requires()
            ctx = rt._begin_chat_turn(
                req.thread_id, user_id, module="consult",
                agent_id="consult_orchestrator", user_text=req.question,
                user_metadata={"mentions": mentions, "attachments": attachment_blocks}
                if (mentions or attachment_blocks) else None,
                effective_tools=effective,
            )
            try:
                from langchain_core.messages import HumanMessage

                from careercrew_core.supervisor.consult_orchestrator import (
                    USER_INPUT_FIELDS,
                    build_consult_orchestrator_graph,
                    synthesize_fallback,
                )

                try:
                    pending_id = rt.record_user_message(
                        user_id, req.thread_id, req.question, module="consult"
                    )
                except Exception:
                    pending_id = None

                # 合并用户已有画像（能力画像/偏好）与本次表单提交：已有信息不再重复询问。
                # 读取失败（后端未初始化等）则退化为仅用请求携带的 profile。
                merged_profile: dict[str, str] = {}
                try:
                    from careercrew_core.memory.semantic import SemanticFactStore

                    store = SemanticFactStore(rt.memory_db, user_id)
                    model = store.load(user_id)
                    merged_profile = _profile_from_model(model)
                except Exception:
                    merged_profile = {}
                if req.profile:
                    for k, v in req.profile.items():
                        if v not in (None, ""):
                            merged_profile[k] = str(v)
                    _persist_form_profile(rt, user_id, req.profile)

                # 画像中已非空字段 = 已知字段；下发 input_request 时过滤掉，不重复弹窗询问
                known_fields = {
                    f["id"] for f in USER_INPUT_FIELDS
                    if (merged_profile.get(f["id"]) or "").strip()
                }

                profile_lines = [
                    f"{f['label']}：{merged_profile[f['id']]}"
                    for f in USER_INPUT_FIELDS
                    if (merged_profile.get(f["id"]) or "").strip()
                ]
                profile_text = "；".join(profile_lines)

                question = req.question.strip()
                if profile_text:
                    context = (
                        f"{question}\n\n（用户已有以下画像信息，请基于此直接给出建议，不要再询问这些内容）\n{profile_text}"
                        if question
                        else f"用户已有以下画像信息，请基于此给出建议：\n{profile_text}"
                    )
                else:
                    context = question

                # T3.2：附件内容 + 引用简历文本并入会诊上下文（展示层仍只显示原 question）
                context = build_user_message(
                    context, attachment_blocks + rt._mention_blocks(user_id, mentions)
                )

                initial_state = {
                    "thread_id": req.thread_id,
                    "user_id": user_id,
                    "stage": "consult",
                    "user_intent": context,
                    "messages": [HumanMessage(content=context)],
                    "pending_action": None,
                    "agent_outputs": {},
                    "target_companies": [],
                    "synthesis": "",
                    "orchestrator_round": 0,
                    "total_agent_calls": 0,
                    "next_agents": [],
                    "agent_tasks": {},
                    "consult_calls": [],
                    "pending_user_entry_id": pending_id,
                    "needs_user_input": False,
                    "input_fields": [],
                    "user_profile": profile_text,
                }
                graph = build_consult_orchestrator_graph(
                    rt.llm,
                    lambda name, cb: rt.new_consult_agent(
                        name, cb, episodic=rt._get_episodic(req.thread_id, user_id),
                        allowed=effective, hitl_requires=hitl,
                    ),
                    emit=_safe_emit,
                )
                result = graph.invoke(initial_state)

                calls = list(result.get("consult_calls") or [])
                opinions: dict[str, str] = {}
                for call in calls:
                    name = call.get("agent")
                    if name:
                        opinions[name] = call.get("content", "")
                # agent_outputs 作为兜底，避免某些实现不返回 consult_calls 时丢失顾问意见。
                outputs = result.get("agent_outputs") or {}
                for name, out in outputs.items():
                    if name not in opinions and isinstance(out, dict) and out.get("content"):
                        opinions[name] = str(out["content"])

                final = (result.get("synthesis") or "").strip()
                if not final:
                    final = synthesize_fallback(opinions, req.question, rt.llm)

                # 总调度官判断信息不足：推 input_request 事件，前端据此弹出资料填写框。
                # 画像中已有的字段过滤掉，只询问缺失信息。
                if result.get("needs_user_input"):
                    wanted = set(result.get("input_fields") or [])
                    fields = [
                        {"id": f["id"], "label": f["label"], "placeholder": f.get("placeholder", ""), "required": bool(f.get("required", False))}
                        for f in USER_INPUT_FIELDS
                        if f["id"] in wanted and f["id"] not in known_fields
                    ]
                    if fields:
                        _safe_emit({
                            "type": "input_request",
                            "message": final or "请先补充以下基本信息，我再为你做针对性规划。",
                            "fields": fields,
                        })

                # synthesis 流式
                _safe_emit({"type": "stage", "stage": "synthesis"})
                for p in _chunk_text(final):
                    _safe_emit({"type": "chunk", "text": p})

                try:
                    rt.record_thread_messages(
                        user_id, req.thread_id,
                        user_text="", agent_text=final,
                        module="consult",
                        metadata={"consult_calls": calls},
                    )
                except Exception:
                    pass  # transcript 写入失败不阻塞会诊
                # T3.5：会诊顾问被 HITL 拦截的调用（blocked_tool_calls）汇总后落
                # awaiting_confirmation 行，与会诊调度过程一并可视化（block-and-record）。
                from careercrew_api.runtime import _observability_from_result

                obs_tool_calls: list[dict] = []
                for call in calls:
                    blocked = call.get("blocked_tool_calls") or []
                    if blocked:
                        synth = type("R", (), {
                            "input_tokens": None, "output_tokens": None,
                            "tool_call_details": [],
                            "blocked_tool_calls": blocked,
                        })()
                        obs_tool_calls.extend(_observability_from_result(synth)["tool_calls"])
                rt._finish_chat_turn(
                    ctx, final, metadata={"opinions": opinions, "calls": calls},
                    langsmith_run_id=ls_run_id,
                    tool_calls=obs_tool_calls or None,
                )
                _safe_emit({
                    "type": "done", "content": final, "opinions": opinions, "calls": calls,
                    **turn_done_fields(ctx),
                })
            except StreamCancelled:
                rt._cancel_chat_turn(ctx)
                pass  # 客户端断开/停止生成：不再投递任何事件
            except Exception as e:
                rt._fail_chat_turn(ctx, e)
                err["exc"] = e
            finally:
                put_guaranteed(q, _SENTINEL, cancel)

        def _worker():
            traced_call(
                _worker_impl,
                name="careercrew.consult",
                run_type="chain",
                run_metadata={"endpoint": "consult"},
            )

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

        try:
            yield _ndjson_line({"type": "stage", "stage": "consult"})
            while True:
                try:
                    # salary_query 等真实抓取工具单次可能 5-60s，多顾问并行时
                    # 放宽到统一空闲超时，避免工具执行期被误判为流超时
                    # （前端已有"思考中"指示）。
                    item = q.get(timeout=STREAM_IDLE_TIMEOUT_SECONDS)
                except queue.Empty:
                    yield _ndjson_line({
                        "type": "error",
                        "message": f"回答生成超时（等待超过 {STREAM_IDLE_TIMEOUT_SECONDS:g} 秒无响应），请重试",
                    })
                    break
                if item is _SENTINEL:
                    break
                yield _ndjson_line(item)
            if "exc" in err:
                yield _ndjson_line({"type": "error", "message": friendly_error(err["exc"])})
        except RuntimeInitError as e:
            yield _ndjson_line({"type": "error", "message": friendly_error(e)})
        finally:
            cancel.set()  # 生成器关闭（客户端断开/停止）→ 通知 worker 协作式取消
        t.join(timeout=1)

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
