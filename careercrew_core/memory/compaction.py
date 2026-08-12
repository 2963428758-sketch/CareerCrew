"""compaction 基础版（I2-I4）+ Pre-compaction Memory Flush（M2）。

触发：token 占比达阈值（优先用模型真实 usage_metadata，否则字符估算）。
策略：保留区（最近 retention_tokens 原封不动）+ 压缩区（分块总结 -> 合并 ->
写 episodic compaction 条目，带 firstKeptEntryId 标记保留区起点）。
M2：压缩前先用 LLM 抽取关键信息（skills/目标公司/偏好）写语义事实，防压缩丢关键信息。
"""
from __future__ import annotations

import json

from langchain_core.messages import BaseMessage, SystemMessage

from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.types import MemoryEntry
from careercrew_core.tracing.langsmith import traced_call


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
        user_model_store=None,  # M2: SemanticFactStore（压缩前 flush 用）
        user_id: str = "u_001",
    ) -> None:
        self._llm = llm
        self._token_threshold_ratio = token_threshold_ratio
        self._retention_tokens = retention_tokens
        self._max_summary_chunk_tokens = max_summary_chunk_tokens
        self._user_model_store = user_model_store
        self._user_id = user_id

    def should_compact(self, messages: list[BaseMessage], context_limit: int | None = None) -> bool:
        """token 占比达阈值即触发（I2）。"""
        if not messages:
            return False
        limit = context_limit or int(self._retention_tokens / self._token_threshold_ratio)
        total = sum(_msg_tokens(m) for m in messages)
        return total >= limit * self._token_threshold_ratio

    def compact(self, messages, episodic: EpisodicMemory) -> tuple[list[BaseMessage], MemoryEntry | None]:
        """保留区 + 压缩区（子 run careercrew.compaction）。"""
        return traced_call(
            self._compact_impl,
            name="careercrew.compaction",
            run_type="chain",
            run_metadata={"endpoint": "compaction"},
            messages=messages,
            episodic=episodic,
        )

    def _compact_impl(self, messages, episodic: EpisodicMemory) -> tuple[list[BaseMessage], MemoryEntry | None]:
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
        if not compressibles:
            return list(messages), None  # 全部都在保留区，无需压缩

        # M2: 压缩前 flush 关键信息到长期记忆（防丢）
        if self._user_model_store is not None:
            self._flush(compressibles)

        summary = self._summarize(compressibles)
        entry = episodic.write(MemoryEntry(type="compaction", content={
            "firstKeptEntryId": _msg_id(kept[0]) if kept else None,
            "summary": summary,
        }))

        new_messages = (
            [SystemMessage(content=f"[历史压缩摘要]\n{summary}")] + kept
            if summary else kept
        )
        return new_messages, entry

    def _flush(self, messages: list[BaseMessage]) -> None:
        """M2: LLM 抽取求职关键信息写语义事实。失败不阻塞压缩。"""
        text = "\n".join(f"{type(m).__name__}: {str(m.content)[:300]}" for m in messages)
        prompt = (
            "从以下对话中抽取求职关键信息，输出 JSON，字段："
            '{"skills": [...], "target_companies": [...], "preferences": {"salary_min": 数字, "city": [...]}}。'
            "没有的信息用空值，只输出 JSON。\n" + text
        )
        try:
            resp = self._llm.invoke(prompt)
            content = resp.content if isinstance(resp.content, str) else str(resp.content)
            data = json.loads(content[content.find("{"): content.rfind("}") + 1])
        except Exception:
            return  # 抽取失败不阻塞压缩
        fields: dict = {}
        if data.get("skills"):
            fields["profile.skills"] = data["skills"]
        if data.get("target_companies"):
            fields["target_companies"] = data["target_companies"]
        pref = data.get("preferences") or {}
        if pref.get("salary_min"):
            fields["preferences.salary_min"] = pref["salary_min"]
        if pref.get("city"):
            fields["preferences.city"] = pref["city"]
        if fields:
            try:
                self._user_model_store.update(self._user_id, fields)
            except Exception:
                pass

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
