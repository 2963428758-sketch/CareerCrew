"""consult 路由：多 agent 并行会诊 + 综合。

事件流：{stage:consult} -> {agent_start} -> {chunk,agent}×n -> {agent_end}
       -> {stage:synthesis} -> synthesis chunk -> {done, opinions, synthesis}
"""
from __future__ import annotations

import json
import queue
import threading
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from careercrew_api.deps import get_runtime_dep
from careercrew_api.runtime import CareerCrewRuntime, RuntimeInitError
from careercrew_api.schemas import ConsultRequest
from careercrew_core.tracing.langsmith import attach_run_metadata, traced_call

router = APIRouter()

_SENTINEL = object()


def _ndjson_line(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False) + "\n"


@router.post("")
def consult(req: ConsultRequest, rt: CareerCrewRuntime = Depends(get_runtime_dep)) -> StreamingResponse:
    """并行会诊：fan-out 各 agent -> join -> synthesis。"""

    def gen() -> Generator[str, None, None]:
        q: queue.Queue = queue.Queue(maxsize=512)
        err: dict[str, BaseException] = {}

        def _worker_impl():
            attach_run_metadata(user_id=req.user_id, stage="consult")
            try:
                from careercrew_core.supervisor.consult import _synthesize, opinion_fallback
                from langchain_core.messages import HumanMessage

                agents = req.agents or ["salary_negotiator", "career_planner"]
                opinions: dict[str, str] = {}

                # 并行跑各 agent
                def _run_one(name: str):
                    q.put({"type": "agent_start", "agent": name})
                    agent = rt.new_consult_agent(name, lambda t, n=name: q.put({"type": "chunk", "text": t, "agent": n}))
                    state = {
                        "thread_id": "consult", "user_id": req.user_id, "stage": "review",
                        "user_intent": req.question,
                        "messages": [HumanMessage(content=req.question)],
                        "pending_action": None, "agent_outputs": {}, "target_companies": [],
                    }
                    agent.run(state)
                    r = agent.last_result
                    content = opinion_fallback(
                        getattr(r, "content", ""), getattr(r, "stopped_reason", "")
                    )
                    opinions[name] = content
                    q.put({"type": "agent_end", "agent": name})

                with ThreadPoolExecutor(max_workers=max(len(agents), 1)) as pool:
                    futures = [pool.submit(_run_one, n) for n in agents]
                    for f in futures:
                        f.result()  # 等待所有完成

                # synthesis 流式
                q.put({"type": "stage", "stage": "synthesis"})

                # synthesis 用 LLM 一次 invoke（不流式），但拆成 chunk 模拟流式
                synth = _synthesize(opinions, req.question, rt.llm)
                # 按句号/换行拆成 chunk，模拟流式体验
                parts = []
                buf = ""
                for ch in synth:
                    buf += ch
                    if ch in "。\n！？!?" or len(buf) >= 20:
                        parts.append(buf)
                        buf = ""
                if buf:
                    parts.append(buf)
                for p in parts:
                    q.put({"type": "chunk", "text": p})

                q.put({"type": "done", "content": synth, "opinions": opinions})
            except Exception as e:
                err["exc"] = e
            finally:
                q.put(_SENTINEL)

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
                    item = q.get(timeout=60.0)
                except queue.Empty:
                    yield _ndjson_line({"type": "error", "message": "stream timeout after 60s"})
                    break
                if item is _SENTINEL:
                    break
                yield _ndjson_line(item)
            if "exc" in err:
                yield _ndjson_line({"type": "error", "message": str(err["exc"])})
        except RuntimeInitError as e:
            yield _ndjson_line({"type": "error", "message": str(e)})
        t.join(timeout=1)

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
