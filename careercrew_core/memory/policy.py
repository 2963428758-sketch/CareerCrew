"""记忆治理：Codex 式生成/使用分离开关（全局 + 用户级）。

全局开关控制特性是否可用；用户级策略控制该用户记忆是否写入/注入。
记忆默认关闭：settings.memory.enabled=false 或用户 enabled=false 时，
不生成新记忆、不自动注入；显式开启才生效。
"""
from __future__ import annotations

from careercrew_core.memory.db import MemoryDb
from careercrew_core.memory.types import MemoryPolicy


class MemoryPolicyStore:
    def __init__(self, db: MemoryDb) -> None:
        self._db = db

    def global_policy(self) -> MemoryPolicy:
        row = self._db.get_global_policy()
        return MemoryPolicy.model_validate(
            {**row, "user_id": "__global__", "updated_at": row.get("updated_at", "")}
        )

    def set_global(self, enabled: bool, generate: bool | None = None, use: bool | None = None) -> MemoryPolicy:
        cur = self.global_policy()
        row = self._db.set_global_policy(
            enabled=enabled,
            generate=cur.generate if generate is None else generate,
            use=cur.use if use is None else use,
        )
        return MemoryPolicy.model_validate(
            {**row, "user_id": "__global__", "updated_at": row.get("updated_at", "")}
        )

    def user_policy(self, user_id: str) -> MemoryPolicy:
        row = self._db.get_policy(user_id)
        return MemoryPolicy.model_validate(row)

    def set_user(
        self,
        user_id: str,
        enabled: bool | None = None,
        generate: bool | None = None,
        use: bool | None = None,
    ) -> MemoryPolicy:
        cur = self.user_policy(user_id)
        row = self._db.set_policy(
            user_id=user_id,
            enabled=cur.enabled if enabled is None else enabled,
            generate=cur.generate if generate is None else generate,
            use=cur.use if use is None else use,
        )
        return MemoryPolicy.model_validate(row)

    def effective(self, user_id: str, feature_enabled: bool) -> MemoryPolicy:
        """生效策略：全局特性关 -> 全关；否则用用户策略。"""
        g = self.global_policy()
        u = self.user_policy(user_id)
        return MemoryPolicy(
            user_id=user_id,
            enabled=bool(feature_enabled and g.enabled and u.enabled),
            generate=bool(feature_enabled and g.enabled and g.generate and u.generate),
            use=bool(feature_enabled and g.enabled and g.use and u.use),
            updated_at=u.updated_at,
        )
