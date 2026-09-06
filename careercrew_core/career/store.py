"""Career store (PostgreSQL). Schema installed by migration 0005 only.

与 PreparationStore 同一套约定：参数化 SQL + owner 作用域 + 连接池事务。
看板状态内嵌在 preparation_opportunities 行上；变更历史单独记录。
"""
import json
from datetime import datetime
from uuid import uuid4

from careercrew_core.career.models import (
    STAGES,
    ActionItemInput,
    BoardStatusInput,
    CareerProfileInput,
    ContactInput,
    HRFollowupInput,
    HRReplyDraftInput,
    MaterialInput,
    OfferInput,
    RealInterviewInput,
    validate_date,
)
from careercrew_core.pg_pool import get_shared_pool

_BOARD_COLUMNS = (
    "id AS opportunity_id, company, title, stage, next_action, next_action_date, note,"
    " stage_updated_at, updated_at"
)


_JSON_KEYS = {"tags", "questions", "weak_points", "report", "result"}


def _public(row):
    if row is None:
        return None
    out = {}
    for key, value in dict(row).items():
        if isinstance(value, datetime):
            value = value.isoformat()
        elif key in _JSON_KEYS and isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                pass
        out[key] = value
    return out


def _public_list(rows):
    return [_public(row) for row in rows]


class CareerStore:
    def __init__(self, dsn: str = "", *, pool=None):
        if pool is None and not dsn.strip():
            raise ValueError("求职跟进存储需要 DATABASE_URL")
        self.pool = pool if pool is not None else get_shared_pool(dsn)

    def _one(self, sql, params):
        with self.pool.connection() as conn:
            return _public(conn.execute(sql, params).fetchone())

    def _all(self, sql, params):
        with self.pool.connection() as conn:
            return _public_list(conn.execute(sql, params).fetchall())

    # ── 看板 ──

    def list_board(self, owner_id: str):
        return self._all(
            f"SELECT {_BOARD_COLUMNS} FROM preparation_opportunities "
            "WHERE owner_id=%s AND archived_at IS NULL "
            "ORDER BY stage_updated_at DESC, id DESC", (owner_id,))

    def get_board_row(self, owner_id: str, opportunity_id: str):
        return self._one(
            f"SELECT {_BOARD_COLUMNS} FROM preparation_opportunities "
            "WHERE owner_id=%s AND id=%s", (owner_id, opportunity_id))

    def update_board(self, owner_id: str, opportunity_id: str, data: dict) -> dict | None:
        payload = BoardStatusInput.model_validate(data)
        if payload.stage not in STAGES:
            return None
        row = self._one(
            """UPDATE preparation_opportunities SET stage=%s, next_action=%s,
               next_action_date=%s, note=%s, applied_version_id=%s,
               stage_updated_at=CURRENT_TIMESTAMP
               WHERE owner_id=%s AND id=%s AND archived_at IS NULL RETURNING id, stage""",
            (payload.stage, payload.next_action, payload.next_action_date,
             payload.note, payload.applied_version_id, owner_id, opportunity_id))
        if row is None:
            return None
        return row

    def record_stage_change(self, owner_id: str, opportunity_id: str,
                            from_stage: str, to_stage: str, note: str = "") -> dict:
        return self._one(
            """INSERT INTO opportunity_stage_log (id, owner_id, opportunity_id, from_stage, to_stage, note)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING id, from_stage, to_stage, note, created_at""",
            (str(uuid4()), owner_id, opportunity_id, from_stage, to_stage, note[:500]))

    def list_stage_changes(self, owner_id: str, opportunity_id: str):
        return self._all(
            "SELECT id, from_stage, to_stage, note, created_at FROM opportunity_stage_log "
            "WHERE owner_id=%s AND opportunity_id=%s ORDER BY created_at DESC, id DESC",
            (owner_id, opportunity_id))

    def archive_opportunity(self, owner_id: str, opportunity_id: str) -> bool:
        return self._one(
            "UPDATE preparation_opportunities SET archived_at=CURRENT_TIMESTAMP "
            "WHERE owner_id=%s AND id=%s AND archived_at IS NULL RETURNING id",
            (owner_id, opportunity_id)) is not None

    # ── 素材库 ──

    def create_material(self, owner_id: str, data: dict):
        payload = MaterialInput.model_validate(data)
        import json

        return self._one(
            """INSERT INTO project_materials (id, owner_id, name, background, role, actions, results, tags, confirmed)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (str(uuid4()), owner_id, payload.name, payload.background, payload.role,
             payload.actions, payload.results, json.dumps(payload.tags, ensure_ascii=False),
             payload.confirmed))

    def list_materials(self, owner_id: str):
        return self._all(
            "SELECT * FROM project_materials WHERE owner_id=%s ORDER BY updated_at DESC, id DESC",
            (owner_id,))

    def update_material(self, owner_id: str, material_id: str, data: dict):
        payload = MaterialInput.model_validate(data)
        import json

        return self._one(
            """UPDATE project_materials SET name=%s, background=%s, role=%s, actions=%s,
               results=%s, tags=%s, confirmed=%s, updated_at=CURRENT_TIMESTAMP
               WHERE owner_id=%s AND id=%s RETURNING *""",
            (payload.name, payload.background, payload.role, payload.actions,
             payload.results, json.dumps(payload.tags, ensure_ascii=False),
             payload.confirmed, owner_id, material_id))

    def delete_material(self, owner_id: str, material_id: str) -> bool:
        return self._one(
            "DELETE FROM project_materials WHERE owner_id=%s AND id=%s RETURNING id",
            (owner_id, material_id)) is not None

    # ── 行动任务 ──

    def create_task(self, owner_id: str, data: dict):
        payload = ActionItemInput.model_validate(data)
        return self._one(
            """INSERT INTO action_items (id, owner_id, title, note, due_date, opportunity_id)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
            (str(uuid4()), owner_id, payload.title, payload.note,
             payload.due_date, payload.opportunity_id))

    def list_tasks(self, owner_id: str, opportunity_id: str | None = None):
        if opportunity_id:
            return self._all(
                "SELECT * FROM action_items WHERE owner_id=%s AND opportunity_id=%s "
                "ORDER BY done ASC, due_date ASC, updated_at DESC, id DESC",
                (owner_id, opportunity_id))
        return self._all(
            "SELECT * FROM action_items WHERE owner_id=%s "
            "ORDER BY done ASC, due_date ASC, updated_at DESC, id DESC", (owner_id,))

    def complete_task(self, owner_id: str, task_id: str, done: bool):
        done_sql = "CURRENT_TIMESTAMP" if done else "NULL"
        return self._one(
            f"""UPDATE action_items SET done=%s, done_at={done_sql},
                updated_at=CURRENT_TIMESTAMP
                WHERE owner_id=%s AND id=%s RETURNING *""",
            (done, owner_id, task_id))

    def postpone_task(self, owner_id: str, task_id: str, due_date: str):
        validate_date(due_date)
        return self._one(
            """UPDATE action_items SET due_date=%s, postponed_count=postponed_count+1,
               done=FALSE, done_at=NULL, updated_at=CURRENT_TIMESTAMP
               WHERE owner_id=%s AND id=%s RETURNING *""",
            (due_date, owner_id, task_id))

    def dismiss_task(self, owner_id: str, task_id: str, dismissed: bool):
        return self._one(
            "UPDATE action_items SET dismissed=%s, updated_at=CURRENT_TIMESTAMP "
            "WHERE owner_id=%s AND id=%s RETURNING *",
            (dismissed, owner_id, task_id))

    def delete_task(self, owner_id: str, task_id: str) -> bool:
        return self._one(
            "DELETE FROM action_items WHERE owner_id=%s AND id=%s RETURNING id",
            (owner_id, task_id)) is not None

    # ── HR 跟进 ──

    def create_followup(self, owner_id: str, data: dict):
        payload = HRFollowupInput.model_validate(data)
        return self._one(
            """INSERT INTO hr_followups (id, owner_id, company, title, channel, content,
               received_at, opportunity_id, todo_note)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (str(uuid4()), owner_id, payload.company, payload.title, payload.channel,
             payload.content, payload.received_at, payload.opportunity_id, payload.todo_note))

    def list_followups(self, owner_id: str):
        return self._all(
            "SELECT * FROM hr_followups WHERE owner_id=%s ORDER BY updated_at DESC, id DESC",
            (owner_id,))

    def set_reply_draft(self, owner_id: str, followup_id: str, data: dict):
        payload = HRReplyDraftInput.model_validate(data)
        return self._one(
            """UPDATE hr_followups SET reply_draft=%s, draft_confirmed=%s, updated_at=CURRENT_TIMESTAMP
               WHERE owner_id=%s AND id=%s RETURNING *""",
            (payload.reply_draft, payload.confirmed, owner_id, followup_id))

    def resolve_followup(self, owner_id: str, followup_id: str, resolved: bool):
        return self._one(
            "UPDATE hr_followups SET resolved=%s, updated_at=CURRENT_TIMESTAMP "
            "WHERE owner_id=%s AND id=%s RETURNING *",
            (resolved, owner_id, followup_id))

    def delete_followup(self, owner_id: str, followup_id: str) -> bool:
        return self._one(
            "DELETE FROM hr_followups WHERE owner_id=%s AND id=%s RETURNING id",
            (owner_id, followup_id)) is not None

    # ── Offer 对比 ──

    def create_offer(self, owner_id: str, data: dict):
        payload = OfferInput.model_validate(data)
        return self._one(
            """INSERT INTO offer_comparisons (id, owner_id, company, title, base_salary, bonus,
               equity, location, work_mode, growth, notes, opportunity_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (str(uuid4()), owner_id, payload.company, payload.title, payload.base_salary,
             payload.bonus, payload.equity, payload.location, payload.work_mode,
             payload.growth, payload.notes, payload.opportunity_id))

    def list_offers(self, owner_id: str):
        return self._all(
            "SELECT * FROM offer_comparisons WHERE owner_id=%s ORDER BY updated_at DESC, id DESC",
            (owner_id,))

    def update_offer(self, owner_id: str, offer_id: str, data: dict):
        payload = OfferInput.model_validate(data)
        return self._one(
            """UPDATE offer_comparisons SET company=%s, title=%s, base_salary=%s, bonus=%s,
               equity=%s, location=%s, work_mode=%s, growth=%s, notes=%s, opportunity_id=%s,
               updated_at=CURRENT_TIMESTAMP WHERE owner_id=%s AND id=%s RETURNING *""",
            (payload.company, payload.title, payload.base_salary, payload.bonus,
             payload.equity, payload.location, payload.work_mode, payload.growth,
             payload.notes, payload.opportunity_id, owner_id, offer_id))

    def delete_offer(self, owner_id: str, offer_id: str) -> bool:
        return self._one(
            "DELETE FROM offer_comparisons WHERE owner_id=%s AND id=%s RETURNING id",
            (owner_id, offer_id)) is not None

    # ── 真实面试复盘 ──

    def create_real_interview(self, owner_id: str, data: dict):
        payload = RealInterviewInput.model_validate(data)
        import json

        weak_points = sorted({
            q.reflection.strip() for q in payload.questions if q.reflection.strip()
        })
        return self._one(
            """INSERT INTO real_interview_records (id, owner_id, company, title, interview_date,
               stage, questions, overall_reflection, weak_points)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (str(uuid4()), owner_id, payload.company, payload.title, payload.interview_date,
             payload.stage, json.dumps([q.model_dump() for q in payload.questions], ensure_ascii=False),
             payload.overall_reflection, json.dumps(weak_points, ensure_ascii=False)))

    def list_real_interviews(self, owner_id: str):
        return self._all(
            "SELECT * FROM real_interview_records WHERE owner_id=%s "
            "ORDER BY created_at DESC, id DESC", (owner_id,))

    def delete_real_interview(self, owner_id: str, record_id: str) -> bool:
        return self._one(
            "DELETE FROM real_interview_records WHERE owner_id=%s AND id=%s RETURNING id",
            (owner_id, record_id)) is not None

    # ── 面试复盘报告 ──

    def save_interview_report(self, owner_id: str, thread_id: str, report: dict):
        import json

        return self._one(
            """INSERT INTO interview_reports (id, owner_id, thread_id, report)
               VALUES (%s,%s,%s,%s) RETURNING id, thread_id, report, created_at""",
            (str(uuid4()), owner_id, thread_id, json.dumps(report, ensure_ascii=False)))

    def list_interview_reports(self, owner_id: str, thread_id: str | None = None):
        if thread_id:
            return self._all(
                "SELECT id, thread_id, report, created_at FROM interview_reports "
                "WHERE owner_id=%s AND thread_id=%s ORDER BY created_at DESC",
                (owner_id, thread_id))
        return self._all(
            "SELECT id, thread_id, report, created_at FROM interview_reports "
            "WHERE owner_id=%s ORDER BY created_at DESC LIMIT 50", (owner_id,))

    # ── 可解释匹配分析 ──

    def save_gap_analysis(self, owner_id: str, opportunity_id: str, version_id: str, result: dict):
        import json

        return self._one(
            """INSERT INTO gap_analyses (id, owner_id, opportunity_id, version_id, result)
               VALUES (%s,%s,%s,%s,%s) RETURNING id, opportunity_id, version_id, result, created_at""",
            (str(uuid4()), owner_id, opportunity_id, version_id,
             json.dumps(result, ensure_ascii=False)))

    def list_gap_analyses(self, owner_id: str, opportunity_id: str):
        return self._all(
            "SELECT id, opportunity_id, version_id, result, created_at FROM gap_analyses "
            "WHERE owner_id=%s AND opportunity_id=%s ORDER BY created_at DESC, id DESC",
            (owner_id, opportunity_id))

    # ── 联系人与内推 ──

    def create_contact(self, owner_id: str, data: dict):
        payload = ContactInput.model_validate(data)
        return self._one(
            """INSERT INTO job_contacts (id, owner_id, company, contact_name, role, channel,
               contact_value, opportunity_id, notes, next_contact_date)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (str(uuid4()), owner_id, payload.company, payload.contact_name, payload.role,
             payload.channel, payload.contact_value, payload.opportunity_id,
             payload.notes, payload.next_contact_date))

    def list_contacts(self, owner_id: str):
        return self._all(
            "SELECT * FROM job_contacts WHERE owner_id=%s ORDER BY updated_at DESC, id DESC",
            (owner_id,))

    def update_contact(self, owner_id: str, contact_id: str, data: dict):
        payload = ContactInput.model_validate(data)
        return self._one(
            """UPDATE job_contacts SET company=%s, contact_name=%s, role=%s, channel=%s,
               contact_value=%s, opportunity_id=%s, notes=%s, next_contact_date=%s,
               updated_at=CURRENT_TIMESTAMP WHERE owner_id=%s AND id=%s RETURNING *""",
            (payload.company, payload.contact_name, payload.role, payload.channel,
             payload.contact_value, payload.opportunity_id, payload.notes,
             payload.next_contact_date, owner_id, contact_id))

    def delete_contact(self, owner_id: str, contact_id: str) -> bool:
        return self._one(
            "DELETE FROM job_contacts WHERE owner_id=%s AND id=%s RETURNING id",
            (owner_id, contact_id)) is not None

    # ── 导师只读分享 ──

    def create_share(self, owner_id: str, kind: str, ref_id: str,
                     expires_at: str, mask_pii: bool) -> dict:
        """创建只读分享令牌（token 由调用方生成的高熵随机串）。"""
        return self._one(
            """INSERT INTO career_share_tokens (token, owner_id, kind, ref_id, mask_pii, expires_at)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
            (str(uuid4()) + str(uuid4()), owner_id, kind, ref_id, mask_pii, expires_at))

    def list_shares(self, owner_id: str):
        return self._all(
            "SELECT token, kind, ref_id, mask_pii, expires_at, revoked_at, created_at "
            "FROM career_share_tokens WHERE owner_id=%s ORDER BY created_at DESC, token DESC",
            (owner_id,))

    def revoke_share(self, owner_id: str, token: str) -> bool:
        return self._one(
            "UPDATE career_share_tokens SET revoked_at=CURRENT_TIMESTAMP "
            "WHERE owner_id=%s AND token=%s AND revoked_at IS NULL RETURNING token",
            (owner_id, token)) is not None

    def resolve_share(self, token: str) -> dict | None:
        """解析令牌：过期或已撤销一律 None（对外统一 404，不泄露状态）。"""
        row = self._one(
            """SELECT token, owner_id, kind, ref_id, mask_pii, expires_at, revoked_at
               FROM career_share_tokens WHERE token=%s""", (token,))
        if row is None or row.get("revoked_at"):
            return None
        from datetime import datetime

        try:
            if datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00")) < datetime.now().astimezone():
                return None
        except ValueError:
            return None
        return row

    # ── 求职画像 ──

    def get_profile(self, owner_id: str):
        return self._one("SELECT * FROM career_profiles WHERE owner_id=%s", (owner_id,))

    def upsert_profile(self, owner_id: str, data: dict):
        payload = CareerProfileInput.model_validate(data)
        return self._one(
            """INSERT INTO career_profiles (owner_id, stage, city, goal, onboarding_done)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (owner_id) DO UPDATE SET stage=EXCLUDED.stage, city=EXCLUDED.city,
                 goal=EXCLUDED.goal, onboarding_done=EXCLUDED.onboarding_done,
                 updated_at=CURRENT_TIMESTAMP
               RETURNING *""",
            (owner_id, payload.stage, payload.city, payload.goal, payload.onboarding_done))

    # ── 统计 / 全局搜索 / 隐私 ──

    def job_search_stats(self, owner_id: str) -> dict:
        with self.pool.connection() as conn:
            stage_rows = conn.execute(
                "SELECT stage, COUNT(*) AS n FROM preparation_opportunities "
                "WHERE owner_id=%s AND archived_at IS NULL GROUP BY stage", (owner_id,)).fetchall()
            transitions = {row["to_stage"]: row["n"] for row in conn.execute(
                "SELECT to_stage, COUNT(*) AS n FROM opportunity_stage_log "
                "WHERE owner_id=%s GROUP BY to_stage", (owner_id,)).fetchall()}
            hr_total = conn.execute(
                "SELECT COUNT(*) AS n FROM hr_followups WHERE owner_id=%s", (owner_id,)).fetchone()
            tasks = conn.execute(
                "SELECT done, COUNT(*) AS n FROM action_items WHERE owner_id=%s "
                "AND dismissed=FALSE GROUP BY done", (owner_id,)).fetchall()
            # 效果归因：按岗位来源（渠道）细分阶段分布，供转化分析（显式样本量）
            source_rows = conn.execute(
                "SELECT COALESCE(NULLIF(source, ''), '未知来源') AS src, stage, COUNT(*) AS n "
                "FROM preparation_opportunities WHERE owner_id=%s AND archived_at IS NULL "
                "GROUP BY src, stage", (owner_id,)).fetchall()
            # 版本归因：按「投递所用简历版本」细分阶段分布（未标记的投递不计入）
            version_rows = conn.execute(
                """SELECT v.label AS vlabel, o.stage, COUNT(*) AS n
                   FROM preparation_opportunities o
                   JOIN preparation_resume_versions v
                     ON v.id = o.applied_version_id AND v.owner_id = o.owner_id
                   WHERE o.owner_id=%s AND o.archived_at IS NULL AND o.applied_version_id <> ''
                   GROUP BY v.label, o.stage""", (owner_id,)).fetchall()
        by_stage = {stage: 0 for stage in STAGES}
        for row in stage_rows:
            by_stage[str(row["stage"])] = int(row["n"])
        by_source: dict[str, dict] = {}
        for row in source_rows:
            src_name = str(row["src"])
            bucket = by_source.setdefault(src_name, {"total": 0, "by_stage": {s: 0 for s in STAGES}})
            bucket["total"] += int(row["n"])
            bucket["by_stage"][str(row["stage"])] = int(row["n"])
        by_version: dict[str, dict] = {}
        for row in version_rows:
            vname = str(row["vlabel"])
            bucket = by_version.setdefault(vname, {"total": 0, "by_stage": {s: 0 for s in STAGES}})
            bucket["total"] += int(row["n"])
            bucket["by_stage"][str(row["stage"])] = int(row["n"])
        applied = int(transitions.get("已投递", 0))
        interviewed = int(transitions.get("面试中", 0))
        offers = int(transitions.get("收到Offer", 0))
        replies = int(hr_total["n"]) if hr_total else 0
        tasks_open = next((int(r["n"]) for r in tasks if not r["done"]), 0)
        tasks_done = next((int(r["n"]) for r in tasks if r["done"]), 0)
        def _rate(numerator: int, denominator: int) -> dict:
            return {"numerator": numerator, "denominator": denominator,
                    "rate": round(numerator / denominator, 4) if denominator else None}
        return {
            "by_stage": by_stage,
            "by_source": by_source,
            "by_version": by_version,
            "applied": applied,
            "replies": replies,
            "interviewed": interviewed,
            "offers": offers,
            "reply_rate": _rate(replies, applied),
            "interview_rate": _rate(interviewed, applied),
            "offer_rate": _rate(offers, applied),
            "tasks": {"open": tasks_open, "done": tasks_done},
        }

    def global_search(self, owner_id: str, query: str) -> dict:
        pattern = f"%{query.strip()}%"
        with self.pool.connection() as conn:
            opportunities = conn.execute(
                "SELECT id, company, title, jd, stage FROM preparation_opportunities "
                "WHERE owner_id=%s AND (company ILIKE %s OR title ILIKE %s OR jd ILIKE %s) "
                "LIMIT 20", (owner_id, pattern, pattern, pattern)).fetchall()
            materials = conn.execute(
                "SELECT id, name, background FROM project_materials "
                "WHERE owner_id=%s AND (name ILIKE %s OR background ILIKE %s OR results ILIKE %s) "
                "LIMIT 20", (owner_id, pattern, pattern, pattern)).fetchall()
            interviews = conn.execute(
                "SELECT id, company, title, overall_reflection FROM real_interview_records "
                "WHERE owner_id=%s AND (company ILIKE %s OR title ILIKE %s OR overall_reflection ILIKE %s) "
                "LIMIT 20", (owner_id, pattern, pattern, pattern)).fetchall()
            offers = conn.execute(
                "SELECT id, company, title, notes FROM offer_comparisons "
                "WHERE owner_id=%s AND (company ILIKE %s OR title ILIKE %s OR notes ILIKE %s) "
                "LIMIT 20", (owner_id, pattern, pattern, pattern)).fetchall()
            tasks = conn.execute(
                "SELECT id, title, note FROM action_items "
                "WHERE owner_id=%s AND (title ILIKE %s OR note ILIKE %s) LIMIT 20",
                (owner_id, pattern, pattern)).fetchall()
        return {
            "opportunities": [dict(r) for r in opportunities],
            "materials": [dict(r) for r in materials],
            "real_interviews": [dict(r) for r in interviews],
            "offers": [dict(r) for r in offers],
            "tasks": [dict(r) for r in tasks],
        }

    def export_all(self, owner_id: str) -> dict:
        with self.pool.connection() as conn:
            def fetch(sql):
                return [dict(r) for r in conn.execute(sql, (owner_id,)).fetchall()]
            return {
                "opportunities": fetch(
                    "SELECT * FROM preparation_opportunities WHERE owner_id=%s"),
                "resume_versions": fetch(
                    "SELECT * FROM preparation_resume_versions WHERE owner_id=%s"),
                "stage_changes": fetch(
                    "SELECT * FROM opportunity_stage_log WHERE owner_id=%s"),
                "materials": fetch("SELECT * FROM project_materials WHERE owner_id=%s"),
                "tasks": fetch("SELECT * FROM action_items WHERE owner_id=%s"),
                "hr_followups": fetch("SELECT * FROM hr_followups WHERE owner_id=%s"),
                "contacts": fetch("SELECT * FROM job_contacts WHERE owner_id=%s"),
                "offers": fetch("SELECT * FROM offer_comparisons WHERE owner_id=%s"),
                "real_interviews": fetch(
                    "SELECT * FROM real_interview_records WHERE owner_id=%s"),
                "profile": fetch("SELECT * FROM career_profiles WHERE owner_id=%s"),
            }

    def purge_all(self, owner_id: str) -> dict:
        """删除本人全部求职跟进与岗位准备数据（账号注销兜底）；返回各类行数。"""
        with self.pool.connection() as conn:
            counts: dict[str, int] = {}
            for table in ("real_interview_records", "offer_comparisons", "hr_followups",
                          "action_items", "project_materials", "interview_reports",
                          "job_contacts"):
                cur = conn.execute(f"DELETE FROM {table} WHERE owner_id=%s RETURNING id",
                                   (owner_id,))
                counts[table] = len(cur.fetchall())
            cur = conn.execute(
                "DELETE FROM preparation_opportunities WHERE owner_id=%s RETURNING id",
                (owner_id,))
            counts["preparation_opportunities"] = len(cur.fetchall())
            cur = conn.execute("DELETE FROM career_profiles WHERE owner_id=%s RETURNING owner_id",
                               (owner_id,))
            counts["career_profiles"] = len(cur.fetchall())
        return counts
