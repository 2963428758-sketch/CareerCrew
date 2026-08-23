"""长期记忆的唯一公共服务边界。

当前实现以既有 semantic_facts / episodic_events 为兼容仓储，先把策略、写入
负规则、分页读取和删除语义集中到同一处；后续表迁移不会改变调用方接口。
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from careercrew_core.memory.episodic import EpisodicMemory
from careercrew_core.memory.policy import MemoryPolicyStore
from careercrew_core.memory.semantic import ALLOWED_FIELDS, SemanticFactStore
from careercrew_core.memory.types import MemoryEntry, SemanticFact, UserModel


_TRANSCRIPT_TYPES = frozenset({"user_message", "agent_response"})
# 仅保留可跨会话复用的、已验证的职业里程碑。自由文本 note、会话开始等
# 低价值记录应走 Conversation，而不是污染长期事件流。
_IMPORTANT_EVENT_TYPES = frozenset({
    "job_match", "application", "hr_reply", "interview_qa", "interview_result", "offer",
})


class MemoryPolicyDenied(PermissionError):
    """调用方试图越过生效 Memory Policy 时抛出。"""


@dataclass(frozen=True)
class EffectiveMemoryPolicy:
    memory_enabled: bool
    can_generate: bool
    can_use: bool
    can_manual_save: bool
    can_consolidate: bool

    def model_dump(self) -> dict[str, bool]:
        return {
            "memory_enabled": self.memory_enabled,
            "can_generate": self.can_generate,
            "can_use": self.can_use,
            "can_manual_save": self.can_manual_save,
            "can_consolidate": self.can_consolidate,
            # 兼容既有 API / 前端字段。
            "enabled": self.memory_enabled,
            "generate": self.can_generate,
            "use": self.can_use,
        }


def _cursor_encode(ts: str, record_id: str) -> str:
    raw = json.dumps([ts, record_id], ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _cursor_decode(cursor: str | None) -> tuple[str, str] | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        ts, record_id = json.loads(base64.urlsafe_b64decode(padded))
        return str(ts), str(record_id)
    except Exception:
        return None


class MemoryService:
    """统一执行长期记忆读写、管理和策略检查。"""

    def __init__(self, db, *, policy_store: MemoryPolicyStore, feature_enabled: bool,
                 vector_index=None, vector_store=None) -> None:
        self._db = db
        self._policy_store = policy_store
        self._feature_enabled = feature_enabled
        self._vector_index = vector_index
        self._vector_store = vector_store
        from careercrew_core.memory.records import LongTermMemoryRepository
        self.records = LongTermMemoryRepository(db)

    def _mirror_fact(self, fact: SemanticFact, *, capture_mode: str) -> None:
        """兼容画像投影的同时维护可演进记录与来源；未执行迁移时不阻断主业务。"""
        from careercrew_core.memory.records import BackfillItem
        item = BackfillItem(
            user_id=fact.user_id, memory_type="semantic", category=fact.type,
            normalized_key=f"semantic:{fact.name.casefold()}", display_text=fact.description or fact.name,
            payload={"value": fact.content, "legacy_name": fact.name}, source_type=fact.source or "service",
            legacy_id=fact.name, occurred_at=fact.modified_at or None,
        )
        try:
            self.records.upsert(item, capture_mode=capture_mode, confidence=fact.confidence)
        except Exception:
            # 旧部署在运行 Alembic 前仍应保持兼容画像可用；管理员可通过回填脚本补齐。
            import logging
            logging.getLogger(__name__).warning("new memory record mirror failed", exc_info=True)

    def _mirror_event(self, user_id: str, entry: MemoryEntry, *, thread_id: str) -> None:
        from careercrew_core.memory.records import BackfillItem
        item = BackfillItem(
            user_id=user_id, memory_type="episodic", category=entry.type,
            normalized_key=f"event:{entry.type}:{entry.id}",
            display_text=f"{entry.type}: {entry.content}",
            payload={"value": entry.content, "thread_id": thread_id}, source_type="verified_event",
            legacy_id=entry.id, occurred_at=entry.ts or None,
        )
        try:
            self.records.upsert(item, capture_mode="verified_event")
        except Exception:
            import logging
            logging.getLogger(__name__).warning("new memory event mirror failed", exc_info=True)

    def effective_policy(self, user_id: str) -> EffectiveMemoryPolicy:
        raw = self._policy_store.effective(user_id, self._feature_enabled)
        enabled = bool(raw.enabled)
        return EffectiveMemoryPolicy(
            memory_enabled=enabled,
            can_generate=bool(enabled and raw.generate),
            can_use=bool(enabled and raw.use),
            can_manual_save=enabled,
            can_consolidate=bool(enabled and raw.generate and raw.use),
        )

    def _require_generate(self, user_id: str, *, manual: bool) -> None:
        policy = self.effective_policy(user_id)
        allowed = policy.can_manual_save if manual else policy.can_generate
        if not allowed:
            action = "手动保存" if manual else "自动生成"
            raise MemoryPolicyDenied(f"当前记忆策略不允许{action}")

    def update_profile(self, user_id: str, fields: dict[str, Any], *, source: str = "api",
                       manual: bool = False) -> UserModel:
        self._require_generate(user_id, manual=manual)
        model = SemanticFactStore(self._db, user_id).update(user_id, fields, source=source)
        store = SemanticFactStore(self._db, user_id)
        for name, value in fields.items():
            if value not in (None, "", []):
                fact = store.get_fact(name)
                if fact is not None:
                    self._mirror_fact(fact, capture_mode="form" if manual else "automatic")
        return model

    def load_profile(self, user_id: str) -> UserModel:
        """用户管理自己的画像不属于 Agent 检索，不受 can_use 限制。"""
        return SemanticFactStore(self._db, user_id).load(user_id)

    def load(self, user_id: str) -> UserModel:
        """JobCycle 兼容适配：Agent 读取画像必须通过 can_use。"""
        if not self.effective_policy(user_id).can_use:
            return UserModel(user_id=user_id)
        return self.load_profile(user_id)

    def save_explicit(self, user_id: str, *, name: str, value: Any,
                      description: str = "") -> SemanticFact:
        """保存用户明确要求记住的事实，generation 关闭时仍允许。"""
        self._require_generate(user_id, manual=True)
        if name in ALLOWED_FIELDS:
            fact_type, content_key = ALLOWED_FIELDS[name]
            content = {content_key: value}
        else:
            fact_type, content = "explicit", {"value": value}
        fact = SemanticFactStore(self._db, user_id).upsert_fact(
            name=name, type=fact_type, content=content, source="explicit",
            confidence=1.0, description=description or f"用户明确要求记住：{name}",
        )
        self._mirror_fact(fact, capture_mode="explicit")
        return fact

    def capture_text_candidates(self, user_id: str, text: str, *, source: str = "conversation") -> list[SemanticFact]:
        """把通过高精度规则的用户自述写为结构化事实。

        普通聊天、泛化问答和临时诉求在候选阶段即被拒绝，且策略关闭时不会读取或写入。
        """
        self._require_generate(user_id, manual=False)
        from careercrew_core.memory.candidates import extract_candidates

        saved: list[SemanticFact] = []
        for candidate in extract_candidates(text):
            model = self.update_profile(user_id, {candidate.field: candidate.value}, source=source)
            field_type, key = ALLOWED_FIELDS[candidate.field]
            fact = SemanticFactStore(self._db, user_id).get_fact(candidate.field)
            if fact is not None:
                saved.append(fact)
        return saved

    def write_event(self, user_id: str, event_type: str, content: dict | str, *,
                    thread_id: str = "memory", parent_id: str | None = None,
                    manual: bool = False) -> MemoryEntry:
        """写入重要事件；普通聊天 transcript 明确拒绝。"""
        if event_type in _TRANSCRIPT_TYPES:
            raise ValueError("普通聊天消息不能写入长期记忆")
        if not manual and event_type not in _IMPORTANT_EVENT_TYPES:
            raise ValueError("仅重要事件类型可以自动写入长期记忆")
        self._require_generate(user_id, manual=manual)
        entry = MemoryEntry(type=event_type, content=content, parentId=parent_id)
        stored = EpisodicMemory(self._db, user_id=user_id, thread_id=thread_id).write(entry)
        self._mirror_event(user_id, stored, thread_id=thread_id)
        if self._vector_index is not None:
            self._vector_index.index_entry(stored)
        return stored

    def list_records(self, user_id: str, *, kind: str = "", category: str = "",
                     query: str = "", limit: int = 20,
                     cursor: str | None = None) -> dict[str, Any]:
        """供管理页面使用的统一、latest-first 游标列表；不受 use 开关限制。"""
        facts = SemanticFactStore(self._db, user_id).list_facts(category or None)
        records: list[dict[str, Any]] = [
            {
                "kind": "fact", "id": fact.name, "type": fact.type,
                "category": fact.type, "ts": fact.modified_at, "content": fact.content,
                "name": fact.name, "description": fact.description, "source": fact.source,
                "confidence": fact.confidence, "version": fact.version,
            }
            for fact in facts
            if not kind or kind == "fact"
        ]
        if not kind or kind == "event":
            for row in self._db.list_episodic(user_id, type=category or None):
                if row.get("type") in _TRANSCRIPT_TYPES:
                    continue
                records.append({
                    "kind": "event", "id": row["id"], "type": row["type"],
                    "category": row["type"], "ts": row["ts"], "content": row.get("content"),
                    "thread_id": row.get("thread_id"), "parentId": row.get("parent_id"),
                })
        if query.strip():
            needle = query.casefold().strip()
            records = [row for row in records if needle in json.dumps(
                row.get("content"), ensure_ascii=False, sort_keys=True
            ).casefold() or needle in str(row.get("description") or "").casefold()]
        records.sort(key=lambda row: (str(row.get("ts") or ""), str(row["id"])), reverse=True)
        total = len(records)
        after = _cursor_decode(cursor)
        if after is not None:
            records = [
                row for row in records
                if (str(row.get("ts") or ""), str(row["id"])) < after
            ]
        limit = max(1, min(int(limit), 100))
        items = records[:limit]
        next_cursor = None
        if len(records) > limit and items:
            last = items[-1]
            next_cursor = _cursor_encode(str(last.get("ts") or ""), str(last["id"]))
        return {"items": items, "next_cursor": next_cursor, "total": total}

    def search(self, user_id: str, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """策略受控的基础检索；管理读取与 Agent 检索保持明确分离。"""
        if not self.effective_policy(user_id).can_use:
            return []
        return self.list_records(user_id, query=query, limit=limit)["items"]

    def delete(self, user_id: str, *, kind: str = "", name: str | None = None,
               entry_id: str | None = None, thread_id: str | None = None,
               category: str = "") -> int:
        """删除数据库记录，并同步请求删除可定位的向量点。"""
        removed = 0
        if kind in ("", "fact") and name:
            removed += SemanticFactStore(self._db, user_id).delete_fact(name)
        elif kind == "fact" and category:
            removed += SemanticFactStore(self._db, user_id).delete_fact(type=category)
        if kind in ("", "event"):
            removed += self._db.delete_episodic(
                user_id, entry_id=entry_id, thread_id=thread_id, type=category or None,
            )
            if self._vector_store is not None:
                if entry_id and hasattr(self._vector_store, "delete_by_ids"):
                    self._vector_store.delete_by_ids([entry_id])
                else:
                    filters: dict[str, Any] = {"user_id": user_id}
                    if entry_id:
                        filters["memory_id"] = entry_id
                    if thread_id:
                        filters["thread_id"] = thread_id
                    if category:
                        filters["type"] = category
                    self._vector_store.delete_by_metadata(filters)
        return removed
