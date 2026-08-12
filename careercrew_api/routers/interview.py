"""interview 路由：出题流式 + 对话式模拟面试 + 评分 + 记录。"""
from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime, RuntimeInitError
from careercrew_api.schemas import (
    InterviewChatMessage,
    InterviewChatRequest,
    QuestionRequest,
    RecordRequest,
    RecordResponse,
    ScoreRequest,
    ScoreResponse,
)
from careercrew_api.sse import done_event, error_event, stage_event, stream_agent

router = APIRouter()

_CHAT_PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "careercrew_ai" / "prompts" / "interviewer_chat.txt"
)


def _ndjson_response(gen: Generator[str, None, None]) -> StreamingResponse:
    return StreamingResponse(
        gen,
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/questions")
def questions(req: QuestionRequest, rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> StreamingResponse:
    """Interviewer agent 出题（rag_query 检索面经/八股），流式输出。"""

    def run_fn(cb):
        from langchain_core.messages import HumanMessage

        agent = rt.new_interviewer(cb)
        prompt = req.topic or "请出一组有梯度的面试题（基础、进阶、场景题各一道）"
        state = {
            "thread_id": req.thread_id, "user_id": req.user_id, "stage": "questions",
            "user_intent": prompt,
            "messages": [HumanMessage(content=prompt)],
            "pending_action": None, "agent_outputs": {}, "target_companies": [],
        }
        agent.run(state)

    def gen() -> Generator[str, None, None]:
        try:
            yield stage_event("questions")
            content_parts: list[str] = []
            for line in stream_agent(run_fn, timeout=120.0):
                evt = json.loads(line)
                if evt["type"] == "chunk":
                    content_parts.append(evt["text"])
                yield line
            content = "".join(content_parts)
            try:
                rt.record_thread_messages(
                    req.user_id, req.thread_id, user_text=prompt, agent_text=content,
                    module="interview",
                )
            except Exception:
                pass
            yield done_event(content)
        except RuntimeInitError as e:
            yield error_event(str(e))
        except Exception as e:
            yield error_event(str(e))

    return _ndjson_response(gen())


def _build_chat_prompt(topic: str, messages: list[InterviewChatMessage]) -> str:
    """把主题 + 对话历史拼成单轮 human 消息（对话式模拟面试）。"""
    parts = [f"当前面试主题：{topic or '（未指定，随机出题）'}"]
    for m in messages:
        who = "用户" if m.role == "user" else "面试官"
        parts.append(f"{who}：{m.content}")
    return "\n\n".join(parts)


@router.post("/chat")
def chat(req: InterviewChatRequest, rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> StreamingResponse:
    """对话式模拟面试：一轮一问；用户回答后评分并追问，done 事件携带 score/feedback。"""

    def run_fn(cb):
        from langchain_core.messages import HumanMessage

        agent = rt.new_interviewer(cb, prompt_path=_CHAT_PROMPT_PATH)
        # 历史由 BaseAgent.history_loader 从 episodic 恢复，这里只放当前输入
        last_user = next(
            (m.content for m in reversed(req.messages) if m.role == "user"),
            "",
        )
        current = (
            f"当前面试主题：{req.topic or '（未指定，随机出题）'}\n\n用户：{last_user}"
            if last_user
            else (req.topic or "请开始模拟面试")
        )
        state = {
            "thread_id": req.thread_id, "user_id": req.user_id, "stage": "questions",
            "user_intent": "chat",
            "messages": [HumanMessage(content=current)],
            "pending_action": None, "agent_outputs": {}, "target_companies": [],
        }
        agent.run(state)

    def gen() -> Generator[str, None, None]:
        try:
            yield stage_event("questions")
            content_parts: list[str] = []
            for line in stream_agent(run_fn, timeout=120.0):
                evt = json.loads(line)
                if evt["type"] == "chunk":
                    content_parts.append(evt["text"])
                yield line
            content = "".join(content_parts)
            extra: dict = {}
            # 用户刚答完一题 -> 从输出解析分数/反馈，随 done 事件下发（首题/总结不带）
            if req.messages and req.messages[-1].role == "user" and "分数" in content:
                from careercrew_core.agents.interviewer import _parse_score

                parsed = _parse_score(content, 10)
                extra = {"score": parsed["score"], "feedback": parsed["feedback"]}
            try:
                last_user = next(
                    (m.content for m in reversed(req.messages) if m.role == "user"), req.topic
                )
                rt.record_thread_messages(
                    req.user_id, req.thread_id, user_text=last_user, agent_text=content,
                    module="interview",
                )
            except Exception:
                pass
            yield done_event(content, **extra)
        except RuntimeInitError as e:
            yield error_event(str(e))
        except Exception as e:
            yield error_event(str(e))

    return _ndjson_response(gen())


@router.post("/score", response_model=ScoreResponse)
def score(req: ScoreRequest, rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> ScoreResponse:
    """LLM 评分 -> {score, feedback}。"""
    result = rt.score_answer(req.question, req.answer, max_score=req.max_score)
    return ScoreResponse(score=result["score"], feedback=result["feedback"])


@router.post("/record", response_model=RecordResponse)
def record(req: RecordRequest, rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> RecordResponse:
    """写 interview_qa 到情景记忆。"""
    saved = rt.record_interview_qa(req.entries)
    return RecordResponse(saved=saved)
