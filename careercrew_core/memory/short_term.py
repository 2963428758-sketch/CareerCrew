"""短期 Context Window 管理（C4）。

compaction（I 阶段）前的简单截断：按 token 估算保留最近消息。
真实 token 用量在 compaction（I 阶段）用模型 usage_metadata，这里用字符数/4 粗估。
"""
from __future__ import annotations

from langchain_core.messages import BaseMessage


def estimate_tokens(messages: list[BaseMessage]) -> int:
    """粗估 token：字符数 / 4 + 每条 4 token overhead。"""
    return sum(len(str(m.content)) // 4 + 4 for m in messages)


class ShortTermMemory:
    """短期对话管理（state.messages 的长度控制）。"""

    def __init__(self, max_tokens: int = 20000) -> None:
        self.max_tokens = max_tokens

    def trim(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """按 token 估算截断，保留最近消息（至少留最近 1 条）。"""
        if estimate_tokens(messages) <= self.max_tokens:
            return list(messages)
        kept: list[BaseMessage] = []
        total = 0
        for m in reversed(messages):
            t = len(str(m.content)) // 4 + 4
            if total + t > self.max_tokens and kept:
                break
            kept.append(m)
            total += t
        return list(reversed(kept))

    def append(self, messages: list[BaseMessage], msg: BaseMessage) -> list[BaseMessage]:
        return list(messages) + [msg]
