"""compaction 基础版（I2-I4）。

触发：token 占比达阈值（优先用模型真实 usage_metadata，否则字符估算）。
策略：保留区（最近 retention_tokens 原封不动）+ 压缩区（分块总结 -> 合并 ->
写 JSONL compaction 条目，带 firstKeptEntryId 标记保留区起点）。
"""
from __future__ import annotations

from langchain_core.messages import BaseMessage, SystemMessage

from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.types import MemoryEntry


def _msg_tokens(msg: BaseMessage) -> int:
    usage = getattr(msg, "usage_metadata", None)
    if usage and usage.get("input_tokens"):
        return int(usage["input_tokens"])
    return len(str(msg.content)) // 4 + 4


def _msg_id(msg: BaseMessage) -> str:
    return getattr(msg, "id", None) or ""


class Compactor:
    def __init__(
        self,
        llm,
        token_threshold_ratio: float = 0.7,
        retention_tokens: int = 20000,
        max_summary_chunk_tokens: int = 4000,
    ) -> None:
        self._llm = llm
        self._token_threshold_ratio = token_threshold_ratio
        self._retention_tokens = retention_tokens
        self._max_summary_chunk_tokens = max_summary_chunk_tokens

    def should_compact(self, messages: list[BaseMessage], context_limit: int | None = None) -> bool:
        """token 占比达阈值即触发（I2）。"""
        if not messages:
            return False
        limit = context_limit or int(self._retention_tokens / self._token_threshold_ratio)
        total = sum(_msg_tokens(m) for m in messages)
        return total >= limit * self._token_threshold_ratio

    def compact(self, messages, episodic: EpisodicMemory) -> tuple[list[BaseMessage], MemoryEntry | None]:
        """保留区 + 压缩区；写 compaction 条目；返回 (新 messages, compaction 条目)。"""
        if not self.should_compact(messages):
            return list(messages), None

        # 从最新往回保留 retention_tokens（保留区）
        kept: list[BaseMessage] = []
        total = 0
        for m in reversed(messages):
            t = _msg_tokens(m)
            if total + t <= self._retention_tokens:
                kept.append(m)
                total += t
            else:
                break
        kept = list(reversed(kept))
        compressibles = messages[: len(messages) - len(kept)]

        summary = self._summarize(compressibles) if compressibles else ""
        entry = episodic.write(MemoryEntry(type="compaction", content={
            "firstKeptEntryId": _msg_id(kept[0]) if kept else None,
            "summary": summary,
        }))

        new_messages = (
            [SystemMessage(content=f"[历史压缩摘要]\n{summary}")] + kept
            if summary else kept
        )
        return new_messages, entry

    def _summarize(self, messages: list[BaseMessage]) -> str:
        """分块总结 -> 合并（I3）。"""
        chunks: list[list[BaseMessage]] = []
        cur: list[BaseMessage] = []
        total = 0
        for m in messages:
            t = _msg_tokens(m)
            if total + t > self._max_summary_chunk_tokens and cur:
                chunks.append(cur)
                cur, total = [m], t
            else:
                cur.append(m)
                total += t
        if cur:
            chunks.append(cur)
        return "\n".join(f"- {self._summarize_chunk(c)}" for c in chunks)

    def _summarize_chunk(self, messages: list[BaseMessage]) -> str:
        text = "\n".join(f"{type(m).__name__}: {str(m.content)[:500]}" for m in messages)
        prompt = f"把以下对话压缩成要点摘要（中文，不超过 200 字）：\n{text}"
        try:
            resp = self._llm.invoke(prompt)
            return resp.content if isinstance(resp.content, str) else str(resp.content)
        except Exception:
            return text[:200]
