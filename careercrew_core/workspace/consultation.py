"""Explainable, owner-scoped consultation reports and execution-plan drafts."""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from typing import Any

from careercrew_core.conversation.store import ConversationStore
from careercrew_core.conversation.uuid7 import uuid7


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


def _tokens(text: str) -> set[str]:
    tokens: set[str] = set(re.findall(r"[a-z0-9_]+", text.casefold()))
    for block in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        tokens.update(block[i:i + 2] for i in range(len(block) - 1))
    return {token for token in tokens if len(token) >= 2}


class ConsultationWorkspace:
    """Turn persisted consult metadata into a reviewable report.

    The report is explanatory rather than a second model call: it is derived
    from the completed assistant message and its already-redacted opinion
    metadata.  Tool arguments, token details, and raw internal call payloads
    are intentionally discarded at the boundary.
    """

    def __init__(self, conversation_store: ConversationStore, *, pool=None) -> None:
        self.conversation_store = conversation_store
        self._db = conversation_store._db
        self._pool = pool
        if self._pool is None and hasattr(self._db, "_get_pool"):
            self._pool = self._db._get_pool()
        self._fake = self._pool is None
        self._lock = threading.RLock()
        self._reports: dict[str, dict] = {}
        self._plans: dict[str, dict] = {}

    def _connect(self):
        if self._pool is None:  # pragma: no cover
            raise RuntimeError("consultation postgres pool is not configured")
        return self._pool.connection()

    def _message(self, owner_id: str, message_id: str) -> dict:
        message = self.conversation_store.get_message(owner_id, message_id)
        if message is None or message.get("role") != "assistant" or message.get("status") != "completed":
            raise PermissionError("会诊回答不存在或不属于当前账号")
        return message

    @staticmethod
    def _metadata(message: dict) -> dict:
        metadata = message.get("metadata")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = {}
        return metadata if isinstance(metadata, dict) else {}

    def build_report(self, owner_id: str, message_id: str) -> dict:
        message = self._message(owner_id, message_id)
        metadata = self._metadata(message)
        opinions_raw = metadata.get("opinions")
        opinions = {
            str(agent): str(content).strip()[:1200]
            for agent, content in (opinions_raw.items() if isinstance(opinions_raw, dict) else [])
            if str(content).strip()
        }
        agent_names = list(opinions)
        threshold = max(2, (len(agent_names) + 1) // 2) if agent_names else 2
        token_agents: dict[str, set[str]] = {}
        for agent, content in opinions.items():
            for token in _tokens(content):
                token_agents.setdefault(token, set()).add(agent)
        consensus = [
            {"point": token, "supporters": sorted(supporters)}
            for token, supporters in sorted(token_agents.items())
            if len(supporters) >= threshold and token not in {"建议", "同时", "需要"}
        ][:20]
        disagreements: list[dict] = []
        for index, left in enumerate(agent_names):
            left_tokens = _tokens(opinions[left])
            for right in agent_names[index + 1:]:
                right_tokens = _tokens(opinions[right])
                overlap = left_tokens & right_tokens
                if not overlap or len(overlap) < max(1, min(len(left_tokens), len(right_tokens)) // 10):
                    disagreements.append({
                        "agents": [left, right],
                        "summary": "两位顾问的侧重点差异较大，需要人工核验",
                    })
        if len(agent_names) > 1 and not disagreements:
            disagreements.append({
                "agents": agent_names,
                "summary": "意见总体接近，仍应确认适用前提和优先级",
            })

        alternatives = [
            {
                "agent": agent,
                "recommendation": content,
                "basis": "来自已完成会诊回答的顾问意见，待人工确认",
            }
            for agent, content in opinions.items()
        ]
        risks: list[dict] = []
        for agent, content in opinions.items():
            if any(word in content for word in ("风险", "注意", "不确定", "可能", "不足")):
                risks.append({"agent": agent, "summary": content[:400]})
        if not risks:
            risks.append({"agent": "system", "summary": "模型会诊是决策草案，执行前需人工核验事实、时效和适用条件"})

        evidence: list[dict] = []
        calls = metadata.get("calls")
        for call in calls if isinstance(calls, list) else []:
            if not isinstance(call, dict):
                continue
            agent = str(call.get("agent") or "unknown")[:100]
            tool = str(call.get("name") or call.get("tool_name") or "")[:120]
            status = str(call.get("status") or "completed")[:40]
            evidence.append({
                "agent": agent,
                "source_type": "consult_agent",
                "tool": tool,
                "status": status,
                "summary": f"{agent} 的会诊调用已记录（{status}）",
            })
        for agent in agent_names:
            if not any(item["agent"] == agent for item in evidence):
                evidence.append({
                    "agent": agent, "source_type": "consult_opinion", "tool": "",
                    "status": "completed", "summary": f"{agent} 提供了独立意见",
                })
        return {
            "source_message_id": message["id"],
            "thread_id": message["thread_id"],
            "source_answer": str(message.get("content") or "")[:1200],
            "opinions": opinions,
            "consensus": consensus,
            "disagreements": disagreements,
            "alternatives": alternatives,
            "risks": risks,
            "evidence": evidence,
            "generated_at": _now(),
        }

    def save_report(self, owner_id: str, message_id: str) -> dict:
        report_json = self.build_report(owner_id, message_id)
        now = _now()
        if self._fake:
            existing = next((row for row in self._reports.values()
                             if row["owner_id"] == owner_id and row["source_message_id"] == message_id), None)
            if existing:
                return self._report_public(existing)
            row = {
                "id": str(uuid7()), "owner_id": owner_id, "source_message_id": message_id,
                "report_json": report_json, "status": "draft", "version": 1,
                "created_at": now, "updated_at": now,
            }
            self._reports[row["id"]] = row
            return self._report_public(row)
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                """
                INSERT INTO consultation_reports
                    (id, owner_id, source_message_id, report_json, status, version, created_at, updated_at)
                VALUES (%s,%s,%s,%s,'draft',1,%s,%s)
                ON CONFLICT (owner_id, source_message_id) DO UPDATE SET updated_at=EXCLUDED.updated_at
                RETURNING *
                """,
                (str(uuid7()), owner_id, message_id, json.dumps(report_json, ensure_ascii=False), now, now),
            ).fetchone()
        return self._report_public(self._row(row))

    def list_reports(self, owner_id: str) -> list[dict]:
        if self._fake:
            rows = [row for row in self._reports.values() if row["owner_id"] == owner_id]
            rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
        else:
            with self._connect() as conn:
                rows = [self._row(row) for row in conn.execute(
                    "SELECT * FROM consultation_reports WHERE owner_id=%s ORDER BY updated_at DESC, id DESC",
                    (owner_id,),
                ).fetchall()]
        return [self._report_public(row) for row in rows]

    def get_report(self, owner_id: str, report_id: str) -> dict | None:
        if self._fake:
            row = self._reports.get(report_id)
            return self._report_public(row) if row and row["owner_id"] == owner_id else None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM consultation_reports WHERE owner_id=%s AND id=%s",
                (owner_id, report_id),
            ).fetchone()
        return self._report_public(self._row(row)) if row else None

    def update_report(self, owner_id: str, report_id: str, *, status: str, version: int) -> dict | None:
        if status not in {"draft", "confirmed"}:
            raise ValueError("报告状态不正确")
        if self._fake:
            row = self._reports.get(report_id)
            if row is None or row["owner_id"] != owner_id:
                return None
            if int(row["version"]) != version:
                raise ValueError("报告版本冲突，请刷新后重试")
            row.update({"status": status, "version": version + 1, "updated_at": _now()})
            return self._report_public(row)
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "UPDATE consultation_reports SET status=%s, version=version+1, updated_at=%s "
                "WHERE owner_id=%s AND id=%s AND version=%s RETURNING *",
                (status, _now(), owner_id, report_id, version),
            ).fetchone()
        if row is None:
            if self.get_report(owner_id, report_id) is not None:
                raise ValueError("报告版本冲突，请刷新后重试")
            return None
        return self._report_public(self._row(row))

    def create_plan(self, owner_id: str, report_id: str, *, title: str,
                    steps: list[dict[str, Any]]) -> dict | None:
        report = self.get_report(owner_id, report_id)
        if report is None:
            return None
        title = str(title or "").strip()
        if not title or len(title) > 200:
            raise ValueError("执行计划标题不能为空且不能超过 200 个字符")
        if not isinstance(steps, list) or not 1 <= len(steps) <= 50:
            raise ValueError("执行计划至少需要 1 个步骤且不超过 50 个")
        clean_steps: list[dict] = []
        for step in steps:
            if not isinstance(step, dict) or not str(step.get("title") or "").strip():
                raise ValueError("每个执行计划步骤都需要标题")
            clean_steps.append({
                "title": str(step["title"]).strip()[:200],
                "note": str(step.get("note") or "").strip()[:1000],
                "status": str(step.get("status") or "open"),
            })
        now = _now()
        row = {
            "id": str(uuid7()), "owner_id": owner_id, "report_id": report_id,
            "title": title, "steps": clean_steps, "status": "draft", "version": 1,
            "created_at": now, "updated_at": now,
        }
        if self._fake:
            self._plans[row["id"]] = row
            return self._plan_public(row)
        with self._connect() as conn, conn.transaction():
            inserted = conn.execute(
                """
                INSERT INTO consultation_plans
                    (id, owner_id, report_id, title, steps_json, status, version, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,'draft',1,%s,%s) RETURNING *
                """,
                (row["id"], owner_id, report_id, title,
                 json.dumps(clean_steps, ensure_ascii=False), now, now),
            ).fetchone()
        return self._plan_public(self._row(inserted))

    def list_plans(self, owner_id: str, report_id: str) -> list[dict]:
        if self._fake:
            rows = [row for row in self._plans.values()
                    if row["owner_id"] == owner_id and row["report_id"] == report_id]
        else:
            with self._connect() as conn:
                rows = [self._row(row) for row in conn.execute(
                    "SELECT * FROM consultation_plans WHERE owner_id=%s AND report_id=%s "
                    "ORDER BY updated_at DESC, id DESC", (owner_id, report_id),
                ).fetchall()]
        return [self._plan_public(row) for row in rows]

    def update_plan(self, owner_id: str, plan_id: str, *, status: str, version: int) -> dict | None:
        if status not in {"draft", "confirmed"}:
            raise ValueError("执行计划状态不正确")
        if self._fake:
            row = self._plans.get(plan_id)
            if row is None or row["owner_id"] != owner_id:
                return None
            if int(row["version"]) != version:
                raise ValueError("执行计划版本冲突，请刷新后重试")
            row.update({"status": status, "version": version + 1, "updated_at": _now()})
            return self._plan_public(row)
        with self._connect() as conn, conn.transaction():
            row = conn.execute(
                "UPDATE consultation_plans SET status=%s, version=version+1, updated_at=%s "
                "WHERE owner_id=%s AND id=%s AND version=%s RETURNING *",
                (status, _now(), owner_id, plan_id, version),
            ).fetchone()
        if row is None:
            return None
        return self._plan_public(self._row(row))

    @staticmethod
    def _row(row: Any) -> dict:
        return _public(dict(row))

    def _report_public(self, row: dict | None) -> dict | None:
        if row is None:
            return None
        result = _public(row) or {}
        payload = result.get("report_json")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        result.pop("owner_id", None)
        result.pop("source_message_id", None)
        result.pop("report_json", None)
        result.update(payload if isinstance(payload, dict) else {})
        return result

    def _plan_public(self, row: dict | None) -> dict | None:
        if row is None:
            return None
        result = _public(row) or {}
        steps = result.pop("steps_json", None)
        if steps is not None and "steps" not in result:
            if isinstance(steps, str):
                try:
                    steps = json.loads(steps)
                except json.JSONDecodeError:
                    steps = []
            result["steps"] = steps
        result.pop("owner_id", None)
        return result
