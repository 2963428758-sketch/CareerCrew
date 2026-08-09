"""interview 路由：出题流式 + 评分 + 记录。"""
from __future__ import annotations

import json
from collections.abc import Generator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime, RuntimeInitError
from careercrew_api.schemas import (
    QuestionRequest,
    RecordRequest,
    RecordResponse,
    ScoreRequest,
    ScoreResponse,
)
from careercrew_api.sse import done_event, error_event, stage_event, stream_agent

router = APIRouter()


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
            "thread_id": "interview", "user_id": req.user_id, "stage": "questions",
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
            yield done_event("".join(content_parts))
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
