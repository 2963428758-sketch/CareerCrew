"""interview 路由：出题流式 + 对话式模拟面试 + 评分 + 记录。"""
from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

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
from careercrew_api.runtime import (
    CareerCrewRuntime,
    _observability_from_result,
)
from careercrew_api.schemas import (
    InterviewChatMessage,
    InterviewChatRequest,
    QuestionRequest,
    RecordRequest,
    RecordResponse,
    ScoreRequest,
    ScoreResponse,
)
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

_CHAT_PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "careercrew_ai" / "prompts" / "interviewer_chat.txt"
)


def _interview_obs(lr) -> dict:
    """从 agent.last_result 抽观测字段，供 _finish_chat_turn 落库（含 rag_query 检索行）。"""
    from careercrew_api.runtime import _rag_query_retrievals

    obs = _observability_from_result(lr)
    details = getattr(lr, "tool_call_details", None) if lr is not None else None
    obs["retrievals"] = _rag_query_retrievals(details or [])
    return {
        "input_tokens": obs["input_tokens"],
        "output_tokens": obs["output_tokens"],
        "total_tokens": obs["total_tokens"],
        "retrievals": obs["retrievals"],
        "tool_calls": obs["tool_calls"],
    }


@router.post("/questions")
def questions(
    req: QuestionRequest,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
    _slot: None = Depends(user_stream_slot),
) -> StreamingResponse:
    """Interviewer agent 出题（rag_query 检索面经/八股），流式输出。

    与其余流式端点一致套 user_stream_slot：每用户并发上限，防止无界并发烧 token。
    """

    mentions = _resolve_mentions(rt, current_user["id"], req.mentions)
    attachment_blocks = _resolve_attachments(rt, current_user["id"], req.attachments)
    effective = rt.compute_effective_tools("interview", req.tools)
    hitl = rt._hitl_requires()

    def gen() -> Generator[str, None, None]:
        result: dict = {"content": "", "turn": None}
        cancel = CancellationEvent()

        def run_fn(cb):
            nonlocal result
            from langchain_core.messages import HumanMessage

            from careercrew_api.attachment_context import build_user_message

            user_id = current_user["id"]
            episodic = rt._get_episodic(req.thread_id, user_id)
            agent = rt.new_interviewer(
                cb, episodic=episodic, allowed=effective, hitl_requires=hitl,
                forced_doc_ids=rt._mention_knowledge_ids(mentions),
            )
            prompt = req.topic or "请出一组有梯度的面试题（基础、进阶、场景题各一道）"
            user_meta: dict | None = None
            if mentions or attachment_blocks:
                user_meta = {}
                if mentions:
                    user_meta["mentions"] = mentions
                if attachment_blocks:
                    user_meta["attachments"] = attachment_blocks
            ctx = rt._begin_chat_turn(
                req.thread_id, user_id, module="interview", agent_id="interviewer",
                user_text=prompt, user_metadata=user_meta,
                effective_tools=effective,
            )
            try:
                pending_id = rt.record_user_message(
                    user_id, req.thread_id, prompt, module="interview"
                )
            except Exception:
                pending_id = None
            state = {
                "thread_id": req.thread_id, "user_id": user_id, "stage": "questions",
                "user_intent": prompt,
                "messages": [HumanMessage(content=build_user_message(
                    prompt, attachment_blocks + rt._mention_blocks(user_id, mentions)
                ))],
                "pending_action": None, "agent_outputs": {}, "target_companies": [],
                "pending_user_entry_id": pending_id,
            }
            cancel.check()
            try:
                agent.run(state)
            except Exception as e:
                rt._fail_chat_turn(ctx, e)
                raise
            cancel.check()
            lr = agent.last_result
            result["content"] = (getattr(lr, "content", "") or "").strip() if lr is not None else ""
            result["turn"] = ctx
            result["lr"] = lr  # T1.4：观测字段随收尾一起落（token / tool_call）

        failed = False
        try:
            yield stage_event("questions")
            content_parts: list[str] = []
            for line in stream_agent(run_fn, cancel=cancel):
                evt = json.loads(line)
                if evt["type"] == "error":
                    failed = True
                elif evt["type"] == "chunk":
                    content_parts.append(evt["text"])
                yield line
            if failed:
                return
            # 最终内容以 agent 最后一轮回答为准：流式 chunk 会包含多轮迭代的
            # "好的，我先检索…"开头话，全部拼接会重复（回归：分布式锁开头重复 3 次）
            content = result["content"] or "".join(content_parts)
            try:
                rt.record_thread_messages(
                    current_user["id"], req.thread_id, user_text="", agent_text=content,
                    module="interview",
                )
            except Exception:
                pass
            rt._finish_chat_turn(result["turn"], content, **_interview_obs(result.get("lr")))
            yield done_event(content, **turn_done_fields(result["turn"]))
        except Exception as e:
            yield error_event(friendly_error(e))

    return _ndjson_response(gen())


def _build_chat_prompt(topic: str, messages: list[InterviewChatMessage]) -> str:
    """把主题 + 对话历史拼成单轮 human 消息（对话式模拟面试）。"""
    parts = [f"当前面试主题：{topic or '（未指定，随机出题）'}"]
    for m in messages:
        who = "用户" if m.role == "user" else "面试官"
        parts.append(f"{who}：{m.content}")
    return "\n\n".join(parts)


@router.post("/chat")
def chat(
    req: InterviewChatRequest,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
    _slot: None = Depends(user_stream_slot),
) -> StreamingResponse:
    """对话式模拟面试：一轮一问；用户回答后评分并追问，done 事件携带 score/feedback。"""

    mentions = _resolve_mentions(rt, current_user["id"], req.mentions)
    attachment_blocks = _resolve_attachments(rt, current_user["id"], req.attachments)
    effective = rt.compute_effective_tools("interview", req.tools)
    hitl = rt._hitl_requires()

    def gen() -> Generator[str, None, None]:
        result: dict = {"content": "", "turn": None}
        cancel = CancellationEvent()

        def run_fn(cb):
            nonlocal result
            from langchain_core.messages import HumanMessage

            from careercrew_api.attachment_context import build_user_message

            user_id = current_user["id"]
            episodic = rt._get_episodic(req.thread_id, user_id)
            agent = rt.new_interviewer(
                cb, episodic=episodic, prompt_path=_CHAT_PROMPT_PATH,
                allowed=effective, hitl_requires=hitl,
                forced_doc_ids=rt._mention_knowledge_ids(mentions),
            )
            # 历史由 BaseAgent.history_loader 从 episodic 恢复，这里只放当前输入
            last_user = next(
                (m.content for m in reversed(req.messages) if m.role == "user"),
                "",
            )
            user_meta: dict | None = None
            if mentions or attachment_blocks:
                user_meta = {}
                if mentions:
                    user_meta["mentions"] = mentions
                if attachment_blocks:
                    user_meta["attachments"] = attachment_blocks
            ctx = rt._begin_chat_turn(
                req.thread_id, user_id, module="interview", agent_id="interviewer_chat",
                user_text=last_user or (req.topic or "请开始模拟面试"),
                user_metadata=user_meta,
                effective_tools=effective,
            )
            try:
                pending_id = rt.record_user_message(
                    user_id, req.thread_id, last_user, module="interview"
                )
            except Exception:
                pending_id = None
            current = (
                f"当前面试主题：{req.topic or '（未指定，随机出题）'}\n\n用户：{last_user}"
                if last_user
                else (req.topic or "请开始模拟面试")
            )
            state = {
                "thread_id": req.thread_id, "user_id": user_id, "stage": "questions",
                "user_intent": "chat",
                "messages": [HumanMessage(content=build_user_message(
                    current, attachment_blocks + rt._mention_blocks(user_id, mentions)
                ))],
                "pending_action": None, "agent_outputs": {}, "target_companies": [],
                "pending_user_entry_id": pending_id,
            }
            cancel.check()
            try:
                agent.run(state)
            except Exception as e:
                rt._fail_chat_turn(ctx, e)
                raise
            cancel.check()
            lr = agent.last_result
            result["content"] = (getattr(lr, "content", "") or "").strip() if lr is not None else ""
            result["turn"] = ctx
            result["lr"] = lr  # T1.4：观测字段随收尾一起落（token / tool_call）

        failed = False
        try:
            yield stage_event("questions")
            content_parts: list[str] = []
            for line in stream_agent(run_fn, cancel=cancel):
                evt = json.loads(line)
                if evt["type"] == "error":
                    failed = True
                elif evt["type"] == "chunk":
                    content_parts.append(evt["text"])
                yield line
            if failed:
                return
            # 最终内容以最后一轮回答为准（流式 chunk 含中间轮开头话，会重复）
            content = result["content"] or "".join(content_parts)
            extra: dict = {}
            # 用户刚答完一题 -> 从输出解析分数/反馈，随 done 事件下发（首题/总结不带）
            if req.messages and req.messages[-1].role == "user" and "分数" in content:
                from careercrew_core.agents.interviewer import _parse_score

                parsed = _parse_score(content, 10)
                extra = {"score": parsed["score"], "feedback": parsed["feedback"]}
            try:
                rt.record_thread_messages(
                    current_user["id"], req.thread_id, user_text="", agent_text=content,
                    module="interview",
                )
            except Exception:
                pass
            rt._finish_chat_turn(result["turn"], content, **_interview_obs(result.get("lr")))
            yield done_event(content, **extra, **turn_done_fields(result["turn"]))
        except Exception as e:
            yield error_event(friendly_error(e))

    return _ndjson_response(gen())


@router.post("/score", response_model=ScoreResponse)
def score(
    req: ScoreRequest,
    _current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> ScoreResponse:
    """LLM 评分 -> {score, feedback}。"""
    result = rt.score_answer(req.question, req.answer, max_score=req.max_score)
    return ScoreResponse(score=result["score"], feedback=result["feedback"])


@router.post("/record", response_model=RecordResponse)
def record(
    req: RecordRequest,
    current_user: CurrentUser,
    rt: CareerCrewRuntime = Depends(get_runtime_dep),
) -> RecordResponse:
    """写 interview_qa 到情景记忆。"""
    saved = rt.record_interview_qa(current_user["id"], req.thread_id, req.entries)
    return RecordResponse(saved=saved)
