"""每用户 LLM 流式并发限制。

流式端点（/match /plan /consult /interview/questions /interview/chat
/resume/generate /resume/chat /knowledge/ask /regenerate）每个请求都消耗真实
LLM token，认证用户若无限制可无限并发打。此处以「每用户信号量」做并发上限：
- 上限默认 2，可用环境变量 MAX_STREAMS_PER_USER 调整；
- 超限返回 429 + 中文提示，不排队不烧钱；
- 通过 FastAPI yield dependency 实现：release 发生在响应体发送完毕之后，
  因此 NDJSON 整条流的生命周期都在配额内。
"""
from __future__ import annotations

import asyncio
import os

from fastapi import HTTPException

from careercrew_api.auth.dependencies import CurrentUser

MAX_STREAMS_PER_USER = max(int(os.environ.get("MAX_STREAMS_PER_USER", "2")), 1)

_sems: dict[str, asyncio.Semaphore] = {}
_sems_lock = asyncio.Lock()


async def user_stream_slot(current_user: CurrentUser) -> None:
    """占用一个该用户的流式并发槽位；响应结束后自动释放。"""
    user_id = current_user["id"]
    async with _sems_lock:
        sem = _sems.get(user_id)
        if sem is None:
            sem = asyncio.Semaphore(MAX_STREAMS_PER_USER)
            _sems[user_id] = sem
    if sem.locked():
        raise HTTPException(
            status_code=429,
            detail=f"该账号已有 {MAX_STREAMS_PER_USER} 个进行中的 AI 会话，请等待完成后再试",
        )
    await sem.acquire()
    try:
        yield
    finally:
        sem.release()
