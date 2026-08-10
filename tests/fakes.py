"""共享测试替身：BaseChatModel 子类假 LLM。

create_agent（LangChain 1.x）要求真实 ``BaseChatModel`` 子类（纯鸭子类型会抛
``NotImplementedError``）；``bind_tools`` 返回 self，``_generate``/``_stream``
按预置响应序列出消息。
"""
from __future__ import annotations

import json

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field


class FakeChatModel(BaseChatModel):
    """按预置响应序列出 AIMessage 的假 LLM（支持 bind_tools 占位 + 流式）。"""

    responses: list[AIMessage] = Field(default_factory=list)

    def __init__(self, responses: list[AIMessage]) -> None:
        super().__init__(responses=list(responses))
        object.__setattr__(self, "_i", 0)

    @property
    def _llm_type(self) -> str:
        return "fake-chat-model"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._next())])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        resp = self._next()
        content = resp.content or ""
        if content:
            for ch in content:
                yield ChatGenerationChunk(message=AIMessageChunk(content=ch))
        if resp.tool_calls:
            chunks = [
                {
                    "name": tc["name"],
                    "args": json.dumps(tc["args"], ensure_ascii=False),
                    "id": tc["id"],
                    "index": i,
                    "type": "tool_call_chunk",
                }
                for i, tc in enumerate(resp.tool_calls)
            ]
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", tool_call_chunks=chunks)
            )

    def _next(self) -> AIMessage:
        i = self._i
        object.__setattr__(self, "_i", i + 1)
        if not self.responses:
            return AIMessage(content="")
        return self.responses[i] if i < len(self.responses) else self.responses[-1]

