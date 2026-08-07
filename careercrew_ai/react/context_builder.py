"""ReAct 上下文组装（B2）。

每轮组装：system prompt + 记忆 preamble（可选，I 阶段注入）+ 短期对话。
工具结果（ToolMessage）由 ReactLoop 在循环中追加，不在此组装。
"""
from __future__ import annotations

from langchain_core.messages import BaseMessage, SystemMessage


class ContextBuilder:
    """组装 ReAct 循环的初始上下文。"""

    def build(
        self,
        system_prompt: str,
        messages: list[BaseMessage],
        memory_preamble: str | None = None,
    ) -> list[BaseMessage]:
        convo: list[BaseMessage] = [SystemMessage(content=system_prompt)]
        if memory_preamble:
            convo.append(SystemMessage(content=f"[相关记忆]\n{memory_preamble}"))
        convo.extend(messages)
        return convo
