"""自动注入（读路径通道一）：agent 调用前注入画像摘要 + 路由事实 + 相关情景事件。

带新鲜度标注（Claude Code 式：旧记忆提示可能过期、需核对）；总 token 预算
由 settings.memory.router.max_inject_tokens 控制（字符估算 len/4）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.policy import MemoryPolicyStore
from careercrew_core.memory.router import MemoryRouter
from careercrew_core.memory.semantic import SemanticFactStore
from careercrew_core.memory.types import SemanticFact
from careercrew_core.memory.vector_index import VectorIndex


def _age_note(modified_at: str) -> str:
    if not modified_at:
        return ""
    try:
        mtime = datetime.fromisoformat(modified_at.replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - mtime).total_seconds() / 86400
    except Exception:
        return ""
    if days <= 1:
        return ""
    return f"（{int(days)} 天前写入，可能已过期，请与用户最新消息核对）"


def _estimate_tokens(text: str) -> int:
    return len(text) // 4 + 8


class MemoryInjector:
    def __init__(
        self,
        db,
        policy_store: MemoryPolicyStore,
        router: MemoryRouter,
        fact_store: SemanticFactStore | None = None,
        episodic: EpisodicMemory | None = None,
        vector_index: VectorIndex | None = None,
        feature_enabled: bool = True,
        max_inject_tokens: int = 2000,
    ) -> None:
        self._db = db
        self._facts = fact_store  # 兼容旧调用；优先按 user_id 动态建
        self._policy = policy_store
        self._router = router
        self._episodic = episodic
        self._vector = vector_index
        self._feature_enabled = feature_enabled
        self._max_tokens = max_inject_tokens

    def build(self, user_id: str, query: str, top_episodes: int = 3) -> str | None:
        """构造注入 preamble；记忆未启用或无可注入内容时返回 None。"""
        policy = self._policy.effective(user_id, self._feature_enabled)
        if not policy.enabled or not policy.use:
            return None
        from careercrew_core.memory.semantic import SemanticFactStore

        facts_store = SemanticFactStore(self._db, user_id) if self._db is not None else self._facts
        parts: list[str] = []
        budget = self._max_tokens

        # 1) 画像摘要（UserModel 投影）
        model = facts_store.load(user_id)
        profile_bits: list[str] = []
        if model.profile.skills:
            profile_bits.append(f"技能: {', '.join(model.profile.skills)}")
        if model.profile.direction:
            profile_bits.append(f"方向: {model.profile.direction}")
        if model.profile.level:
            profile_bits.append(f"级别: {model.profile.level}")
        if model.target_companies:
            profile_bits.append(f"目标公司: {', '.join(model.target_companies)}")
        if model.preferences.city:
            profile_bits.append(f"城市: {', '.join(model.preferences.city)}")
        if model.preferences.salary_min is not None:
            profile_bits.append(f"薪资预期≥{model.preferences.salary_min}K")
        if profile_bits:
            profile_text = "[用户画像]（若与用户最新消息冲突，一律以用户最新消息为准）\n" + "\n".join(profile_bits)
            if _estimate_tokens(profile_text) <= budget:
                parts.append(profile_text)

        # 2) LLM 路由选出的语义事实（带新鲜度标注）
        facts = facts_store.list_facts()
        routed = self._router.select(query, facts) if query else facts[: self._router.top_n]
        fact_lines: list[str] = []
        for f in routed:
            note = _age_note(f.modified_at)
            fact_lines.append(f"- {f.description or f.name}{note}")
        if fact_lines:
            fact_text = "[记忆事实]\n" + "\n".join(fact_lines)
            if _estimate_tokens(fact_text) <= budget:
                parts.append(fact_text)

        # 3) 最近相关情景事件（向量优先，无向量时取最近条目）
        ep_lines: list[str] = []
        if self._vector is not None and query:
            try:
                for e in self._vector.search(query, top_k=top_episodes):
                    ep_lines.append(f"- [{e.type}] {e.content}")
            except Exception:
                pass
        elif self._episodic is not None:
            for e in self._episodic.list(limit=top_episodes):
                ep_lines.append(f"- [{e.type}] {e.content}")
        if ep_lines:
            ep_text = "[相关历史]\n" + "\n".join(ep_lines)
            if _estimate_tokens(ep_text) <= budget:
                parts.append(ep_text)

        if not parts:
            return None
        return "\n\n".join(parts)
