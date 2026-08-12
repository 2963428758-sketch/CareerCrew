"""语义记忆：结构化用户事实（替代单文件 UserModel JSON）。

每条事实 = semantic_facts 一行（name/type/description/content/source/confidence/version），
带来源、置信度、时间戳，支持冲突覆盖留痕（version 递增）。对外保留旧 UserModel
投影契约（load/update 返回 UserModel），供 JobCycle/dashboard/前端复用。
"""
from __future__ import annotations

from careercrew_core.memory.db import MemoryDb
from careercrew_core.memory.types import SemanticFact, UserModel, UserPreferences, UserProfile

# 允许 profile_update 更新的字段路径（白名单；name -> (fact_type, content_key)）
ALLOWED_FIELDS: dict[str, tuple[str, str]] = {
    "profile.skills": ("profile", "skills"),
    "profile.level": ("profile", "level"),
    "profile.direction": ("profile", "direction"),
    "profile.experience_years": ("profile", "experience_years"),
    "target_companies": ("target_company", "companies"),
    "preferences.salary_min": ("preference", "salary_min"),
    "preferences.salary_max": ("preference", "salary_max"),
    "preferences.city": ("preference", "city"),
    "preferences.work_mode": ("preference", "work_mode"),
}


class SemanticFactStore:
    """语义记忆读写（用户级，全部按 user_id 隔离）。"""

    def __init__(self, db: MemoryDb, user_id: str = "u_001") -> None:
        self._db = db
        self.user_id = user_id

    # ── 事实读写 ──

    def list_facts(self, type: str | None = None) -> list[SemanticFact]:
        return [SemanticFact.model_validate(r) for r in self._db.list_facts(self.user_id, type)]

    def get_fact(self, name: str) -> SemanticFact | None:
        row = self._db.get_fact(self.user_id, name)
        return SemanticFact.model_validate(row) if row else None

    def upsert_fact(
        self,
        name: str,
        type: str,
        content: dict,
        source: str = "manual",
        confidence: float = 1.0,
        description: str = "",
    ) -> SemanticFact:
        row = self._db.upsert_fact(
            user_id=self.user_id,
            name=name,
            type=type,
            description=description,
            content=content,
            source=source,
            confidence=confidence,
        )
        return SemanticFact.model_validate(row)

    def delete_fact(self, name: str | None = None, type: str | None = None) -> int:
        return self._db.delete_fact(self.user_id, name=name, type=type)

    # ── 旧 UserModel 兼容投影 ──

    def load(self, user_id: str | None = None) -> UserModel:
        """从事实聚合出 UserModel 投影（无事实时返回默认空画像）。"""
        uid = user_id or self.user_id
        facts = [SemanticFact.model_validate(r) for r in self._db.list_facts(uid)]
        profile_kw: dict = {}
        target_companies: list[str] = []
        pref_kw: dict = {}
        mastery: dict[str, float] = {}
        for f in facts:
            if f.type == "profile":
                profile_kw.update({k: v for k, v in f.content.items() if v is not None})
            elif f.type == "target_company":
                target_companies.extend(f.content.get("companies") or [])
            elif f.type == "preference":
                pref_kw.update({k: v for k, v in f.content.items() if v is not None})
            elif f.type == "mastery":
                mastery.update(f.content.get("mastery") or {})
        return UserModel(
            user_id=uid,
            profile=UserProfile(**profile_kw),
            target_companies=target_companies,
            preferences=UserPreferences(**pref_kw),
            interview_mastery=mastery,
        )

    def update(self, user_id: str, fields: dict, source: str = "profile_update") -> UserModel:
        """结构化更新（白名单校验），每条字段落一条事实，version 递增留痕。"""
        for k in fields:
            if k not in ALLOWED_FIELDS:
                raise ValueError(f"非法字段: {k}，允许: {sorted(ALLOWED_FIELDS)}")
        uid = user_id or self.user_id
        for k, v in fields.items():
            if v is None:
                continue
            ftype, key = ALLOWED_FIELDS[k]
            content = {key: v}
            self._db.upsert_fact(
                user_id=uid, name=k, type=ftype, description=f"用户{k}",
                content=content, source=source, confidence=1.0,
            )
        return self.load(uid)
