"""Safe tool registry operations, policy overrides, and redacted observability."""
from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any

from careercrew_core.conversation.store import ConversationStore
from careercrew_core.conversation.uuid7 import uuid7
from careercrew_core.tools.capabilities import MODULE_TOOLS, TOOL_LABELS
from careercrew_core.tools.effective import compute_effective_tools


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _public(row: dict | None) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    for key, value in list(result.items()):
        if isinstance(value, datetime):
            result[key] = value.isoformat()
    return result


def _failure_category(row: dict) -> str | None:
    if str(row.get("status") or "").lower() not in {"failed", "error", "rejected"}:
        return None
    text = " ".join(str(row.get(key) or "") for key in ("error_type", "error_code", "error_summary")).casefold()
    for category, needles in {
        "timeout": ("timeout", "timed out", "超时"),
        "auth": ("auth", "unauthorized", "forbidden", "401", "403"),
        "rate_limit": ("rate", "429", "quota", "限流"),
        "validation": ("validation", "invalid", "参数", "校验"),
        "permission": ("permission", "denied", "权限"),
        "provider": ("provider", "upstream", "qdrant", "llm"),
    }.items():
        if any(needle in text for needle in needles):
            return category
    return "unknown"


def _safe_error_summary(row: dict) -> str | None:
    if _failure_category(row) is None:
        return None
    return f"失败类别：{_failure_category(row) or 'unknown'}"


def is_tool_store_unavailable(exc: BaseException) -> bool:
    """Identify storage/connection failures that callers should expose as 503."""

    return (
        isinstance(exc, (ConnectionError, TimeoutError, OSError, RuntimeError))
        or exc.__class__.__module__.split(".", 1)[0] == "psycopg"
    )


class ToolOperationsCenter:
    """Global registry policy with user-scoped call history reads.

    A disabled tool is removed from the effective server allowlist; the client
    cannot re-enable it through its requested-tools payload.  MCP entries are
    metadata-only in the health view: this center never creates an unauthenticated
    network probe.
    """

    def __init__(self, conversation_store: ConversationStore, settings, *, pool=None) -> None:
        self.conversation_store = conversation_store
        self._db = conversation_store._db
        self.settings = settings
        self._pool = pool
        if self._pool is None and hasattr(self._db, "_get_pool"):
            self._pool = self._db._get_pool()
        self._fake = self._pool is None
        self._lock = threading.RLock()
        self._policies: dict[str, dict] = {}
        self._audits: list[dict] = []

    def _connect(self):
        if self._pool is None:  # pragma: no cover
            raise RuntimeError("tool operations postgres pool is not configured")
        return self._pool.connection()

    def _registry(self) -> list[dict]:
        registry = getattr(getattr(self.settings, "tools", None), "registry", None)
        internal = list(getattr(registry, "internal", None) or []) if registry else []
        mcp = list(getattr(registry, "mcp", None) or []) if registry else []
        seen: set[str] = set()
        rows: list[dict] = []
        for kind, names in (("internal", internal), ("mcp", mcp)):
            for tool_id in names:
                tool_id = str(tool_id)
                if tool_id in seen:
                    continue
                seen.add(tool_id)
                rows.append({"id": tool_id, "kind": kind})
        return rows

    def _hitl(self) -> set[str]:
        hitl = getattr(getattr(self.settings, "tools", None), "hitl", None)
        return set(getattr(hitl, "requires_confirmation", None) or []) if hitl else set()

    def _policy(self, tool_id: str) -> dict | None:
        if self._fake:
            return self._policies.get(tool_id)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tool_policies WHERE tool_id=%s", (tool_id,)).fetchone()
        return _public(dict(row)) if row else None

    def _enabled(self, tool_id: str) -> bool:
        policy = self._policy(tool_id)
        return bool(policy.get("enabled", True)) if policy else True

    def status(self, module: str = "chat") -> list[dict]:
        allow = set(MODULE_TOOLS.get(module, [])) if module in MODULE_TOOLS else None
        return [
            {
                "id": row["id"],
                "name": TOOL_LABELS.get(row["id"], row["id"]),
                "kind": row["kind"],
                "configured": True,
                "enabled": self._enabled(row["id"]),
                "requires_hitl": row["id"] in self._hitl(),
                "visible_for_module": allow is None or row["id"] in allow,
                "health": "disabled" if not self._enabled(row["id"])
                else ("restricted" if row["kind"] == "mcp" else "ready"),
                "health_detail": "MCP 网络探测仅允许受控服务端路径"
                if row["kind"] == "mcp" else "服务已注册",
            }
            for row in self._registry()
            if allow is None or row["id"] in allow
        ]

    def enabled_registry(self) -> list[str]:
        return [row["id"] for row in self._registry() if self._enabled(row["id"])]

    def effective_tools(self, module: str, requested: list[str] | None) -> list[str]:
        module_allow = MODULE_TOOLS.get(module)
        return compute_effective_tools(
            requested, self.enabled_registry(), module_allowlist=module_allow,
        )

    def set_policy(self, actor_id: str, tool_id: str, enabled: bool, reason: str = "") -> dict:
        if tool_id not in {row["id"] for row in self._registry()}:
            raise ValueError("工具未注册")
        reason = str(reason or "").strip()[:500]
        old = self._policy(tool_id)
        old_enabled = bool(old.get("enabled", True)) if old else True
        now = _now()
        if self._fake:
            self._policies[tool_id] = {
                "tool_id": tool_id, "enabled": bool(enabled), "reason": reason,
                "updated_by": actor_id, "updated_at": now,
            }
            self._audits.append({
                "id": str(uuid7()), "actor_id": actor_id, "tool_id": tool_id,
                "old_enabled": old_enabled, "new_enabled": bool(enabled),
                "reason": reason, "created_at": now,
            })
            return self.status_item(tool_id)
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "INSERT INTO tool_policies(tool_id, enabled, reason, updated_by, updated_at) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT(tool_id) DO UPDATE SET enabled=EXCLUDED.enabled, "
                "reason=EXCLUDED.reason, updated_by=EXCLUDED.updated_by, updated_at=EXCLUDED.updated_at RETURNING *",
                (tool_id, bool(enabled), reason, actor_id, now),
            ).fetchone()
            conn.execute(
                "INSERT INTO tool_policy_audit(id, actor_id, tool_id, old_enabled, new_enabled, reason, created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (str(uuid7()), actor_id, tool_id, old_enabled, bool(enabled), reason, now),
            )
        return self.status_item(tool_id, policy=_public(dict(row)))

    def status_item(self, tool_id: str, *, policy: dict | None = None) -> dict:
        policy = policy if policy is not None else self._policy(tool_id)
        row = next((item for item in self.status() if item["id"] == tool_id), None)
        if row is None:
            raise ValueError("工具未注册")
        if policy is not None:
            row["enabled"] = bool(policy.get("enabled", True))
            row["health"] = "disabled" if not row["enabled"] else (
                "restricted" if row["kind"] == "mcp" else "ready"
            )
        return row

    def call_history(self, owner_id: str, limit: int = 100) -> list[dict]:
        if not 1 <= limit <= 200:
            raise ValueError("调用历史数量必须为 1–200")
        if self._fake:
            runs = {run_id: run for run_id, run in getattr(self._db, "_runs", {}).items()
                    if run.get("user_id") == owner_id}
            rows = [
                {**call, "module": runs[call["run_id"]].get("module"),
                 "agent_id": runs[call["run_id"]].get("agent_id")}
                for call in getattr(self._db, "_tool_calls", {}).values()
                if call.get("run_id") in runs
            ]
            rows.sort(key=lambda row: (str(row.get("created_at") or ""), str(row.get("id") or "")), reverse=True)
        else:
            with self._connect() as conn:
                rows = [dict(row) for row in conn.execute(
                    "SELECT c.id, c.tool_name, c.status, c.duration_ms, c.requires_hitl, c.hitl_status, "
                    "c.error_type, c.error_summary, c.created_at, r.module, r.agent_id "
                    "FROM agent_run_tool_calls c JOIN agent_runs r ON r.id=c.run_id "
                    "WHERE r.user_id=%s ORDER BY c.created_at DESC, c.id DESC LIMIT %s",
                    (owner_id, limit),
                ).fetchall()]
        return [self._call_public(row) for row in rows[:limit]]

    @staticmethod
    def _call_public(row: dict) -> dict:
        return {
            "id": str(row.get("id")), "tool_id": str(row.get("tool_name") or ""),
            "module": row.get("module"), "agent_id": row.get("agent_id"),
            "status": row.get("status"), "duration_ms": row.get("duration_ms"),
            "requires_hitl": bool(row.get("requires_hitl")),
            "hitl_status": row.get("hitl_status"),
            "failure_category": _failure_category(row),
            "error_summary": _safe_error_summary(row),
            "created_at": _public({"created_at": row.get("created_at")})["created_at"],
        }

    def audit(self, actor_id: str | None = None) -> list[dict]:
        if self._fake:
            rows = list(self._audits)
            if actor_id:
                rows = [row for row in rows if row["actor_id"] == actor_id]
            rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
            return rows
        query = "SELECT id, actor_id, tool_id, old_enabled, new_enabled, reason, created_at FROM tool_policy_audit"
        params: tuple = ()
        if actor_id:
            query += " WHERE actor_id=%s"
            params = (actor_id,)
        query += " ORDER BY created_at DESC, id DESC LIMIT 200"
        with self._connect() as conn:
            return [_public(dict(row)) for row in conn.execute(query, params).fetchall()]
