"""后台 consolidation（反思式写入，Auto Dream 式四阶段）。

门控：距上次 ≥ min_interval_hours 且新增会话 ≥ min_sessions（均可配）。
四阶段：orient（盘点现有事实/事件）→ gather（收集信号：近期事件/会话数）
→ consolidate（确定性合并：interview_mastery 按面试得分更新、去重、
低置信度旧事实降级）→ prune（删除过期低置信事实，更新 __consolidation__ 标记）。
失败静默降级，不阻塞主链路。
"""
from __future__ import annotations

from datetime import UTC, datetime

from careercrew_core.memory.db import MemoryDb
from careercrew_core.memory.types import SemanticFact

_MARKER = "__consolidation__"


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Consolidator:
    def __init__(
        self,
        db: MemoryDb,
        min_interval_hours: int = 24,
        min_sessions: int = 5,
        stale_days: int = 30,
        low_confidence: float = 0.5,
    ) -> None:
        self._db = db
        self._min_interval_hours = min_interval_hours
        self._min_sessions = min_sessions
        self._stale_days = stale_days
        self._low_confidence = low_confidence

    def last_state(self, user_id: str) -> dict:
        row = self._db.get_fact(user_id, _MARKER)
        if not row:
            return {"last_consolidated_at": "", "sessions": 0}
        content = row.get("content") or {}
        return {
            "last_consolidated_at": content.get("last_consolidated_at", ""),
            "sessions": int(content.get("sessions", 0)),
        }

    def should_run(self, user_id: str) -> bool:
        state = self.last_state(user_id)
        if not state["last_consolidated_at"]:
            # 首次：需要至少 min_sessions 个会话才有意义
            return self._count_sessions(user_id) >= self._min_sessions
        try:
            last = datetime.fromisoformat(state["last_consolidated_at"].replace("Z", "+00:00"))
            hours = (datetime.now(UTC) - last).total_seconds() / 3600
        except Exception:
            hours = 0.0
        sessions = self._count_sessions(user_id)
        return hours >= self._min_interval_hours and sessions >= self._min_sessions

    def consolidate(self, user_id: str, force: bool = False) -> dict:
        """四阶段合并；未达门控或失败时返回 {"ran": False, "reason": ...}。"""
        try:
            if not force and not self.should_run(user_id):
                return {"ran": False, "reason": "gate_not_met"}
            phases: list[str] = []

            # Phase 1 orient
            facts = [SemanticFact.model_validate(r) for r in self._db.list_facts(user_id)]
            events = self._db.list_episodic(user_id)
            phases.append("orient")

            # Phase 2 gather
            sessions = self._count_sessions(user_id)
            mastery = self._gather_mastery(events)
            phases.append("gather")

            # Phase 3 consolidate
            if mastery:
                self._db.upsert_fact(
                    user_id=user_id, name="interview_mastery", type="mastery",
                    description="各主题面试掌握度（consolidation 聚合）",
                    content={"mastery": mastery}, source="consolidation", confidence=1.0,
                )
            # 去重：同名事实本就 upsert 覆盖；这里把重复 name 的旧条目按版本保留最高
            seen: set[str] = set()
            for f in sorted(facts, key=lambda x: x.version, reverse=True):
                if f.name in seen and f.name != _MARKER:
                    self._db.delete_fact(user_id, name=f.name)
                seen.add(f.name)
            phases.append("consolidate")

            # Phase 4 prune
            pruned = self._prune(user_id, facts)
            self._db.upsert_fact(
                user_id=user_id, name=_MARKER, type="note",
                description="consolidation 运行标记",
                content={"last_consolidated_at": _now(), "sessions": sessions},
                source="consolidation", confidence=1.0,
            )
            phases.append("prune")
            return {"ran": True, "phases": phases, "pruned": pruned, "mastery": bool(mastery)}
        except Exception:
            return {"ran": False, "reason": "error"}

    def _count_sessions(self, user_id: str) -> int:
        events = self._db.list_episodic(user_id)
        return len({e.get("thread_id") for e in events})

    def _gather_mastery(self, events: list[dict]) -> dict[str, float]:
        """按 interview_qa 事件得分聚合掌握度（确定性，topic 取自 content）。"""
        totals: dict[str, list[float]] = {}
        for e in events:
            if e.get("type") != "interview_qa":
                continue
            content = e.get("content") or {}
            if isinstance(content, str):
                content = {"q": content}
            topic = str(content.get("topic") or content.get("q") or "general")[:30]
            try:
                score = float(content.get("score", 0))
            except (TypeError, ValueError):
                score = 0.0
            totals.setdefault(topic, []).append(score)
        return {t: round(sum(v) / len(v), 2) for t, v in totals.items()}

    def _prune(self, user_id: str, facts: list[SemanticFact]) -> int:
        """删除「低置信度 + 超过 stale_days 未更新」的事实（不含 marker/mastery）。"""
        pruned = 0
        now = datetime.now(UTC)
        for f in facts:
            if f.name in (_MARKER, "interview_mastery"):
                continue
            if f.confidence >= self._low_confidence:
                continue
            try:
                mtime = datetime.fromisoformat(f.modified_at.replace("Z", "+00:00"))
                days = (now - mtime).total_seconds() / 86400
            except Exception:
                continue
            if days >= self._stale_days:
                self._db.delete_fact(user_id, name=f.name)
                pruned += 1
        return pruned
