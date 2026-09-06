"""PostgreSQL preparation store. Schema is installed by migration 0004 only.

Pool transactions commit on context exit. INSERT ... SELECT binds the owner,
parent, and snapshot in one statement, including when a parent is edited/deleted
concurrently. Composite foreign keys enforce the same ownership at the DB layer.
"""
from datetime import datetime
from uuid import uuid4

from careercrew_core.pg_pool import get_shared_pool
from careercrew_core.preparation.models import (
    OpportunityInput,
    PreparationSessionInput,
    ResumeVersionInput,
)

_OPPORTUNITY_COLUMNS = "id, company, title, jd, city, salary, source, url, created_at, updated_at"
_VERSION_COLUMNS = "id, opportunity_id, label, content, original_content, created_at"
_SESSION_COLUMNS = "thread_id, module, opportunity_id, resume_version_id, company, title, jd, resume_content, resume_label"


def _public(row):
    if row is None:
        return None
    return {key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in dict(row).items()}


class PreparationStore:
    def __init__(self, dsn: str = "", *, pool=None):
        if pool is None and not dsn.strip():
            raise ValueError("岗位准备存储需要 DATABASE_URL")
        self.pool = pool if pool is not None else get_shared_pool(dsn)

    def _one(self, sql, params):
        with self.pool.connection() as conn:
            return _public(conn.execute(sql, params).fetchone())

    def _all(self, sql, params):
        with self.pool.connection() as conn:
            return [_public(row) for row in conn.execute(sql, params).fetchall()]

    def create_opportunity(self, owner_id: str, data: dict):
        payload = OpportunityInput.model_validate(data)
        return self._one(
            f"""INSERT INTO preparation_opportunities
                (id, owner_id, company, title, jd, city, salary, source, url)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING {_OPPORTUNITY_COLUMNS}""",
            (str(uuid4()), owner_id, payload.company, payload.title, payload.jd,
             payload.city, payload.salary, payload.source, payload.url),
        )

    def list_opportunities(self, owner_id: str):
        return self._all(
            f"SELECT {_OPPORTUNITY_COLUMNS} FROM preparation_opportunities "
            "WHERE owner_id=%s ORDER BY updated_at DESC, id DESC", (owner_id,))

    def get_opportunity(self, owner_id: str, opportunity_id: str):
        return self._one(
            f"SELECT {_OPPORTUNITY_COLUMNS} FROM preparation_opportunities WHERE owner_id=%s AND id=%s",
            (owner_id, opportunity_id))

    def update_opportunity(self, owner_id: str, opportunity_id: str, data: dict):
        payload = OpportunityInput.model_validate(data)
        return self._one(
            f"""UPDATE preparation_opportunities SET company=%s,title=%s,jd=%s,city=%s,
                salary=%s,source=%s,url=%s,updated_at=CURRENT_TIMESTAMP
                WHERE owner_id=%s AND id=%s RETURNING {_OPPORTUNITY_COLUMNS}""",
            (payload.company, payload.title, payload.jd, payload.city, payload.salary,
             payload.source, payload.url, owner_id, opportunity_id))

    def delete_opportunity(self, owner_id: str, opportunity_id: str) -> bool:
        return self._one(
            "DELETE FROM preparation_opportunities WHERE owner_id=%s AND id=%s RETURNING id",
            (owner_id, opportunity_id)) is not None

    def create_version(self, owner_id: str, opportunity_id: str, data: dict):
        payload = ResumeVersionInput.model_validate(data)
        return self._one(
            f"""INSERT INTO preparation_resume_versions
                (id,owner_id,opportunity_id,label,content,original_content)
                SELECT %s,owner_id,id,%s,%s,%s FROM preparation_opportunities
                WHERE owner_id=%s AND id=%s RETURNING {_VERSION_COLUMNS}""",
            (str(uuid4()), payload.label, payload.content, payload.original_content,
             owner_id, opportunity_id))

    def list_versions(self, owner_id: str, opportunity_id: str):
        return self._all(
            f"SELECT {_VERSION_COLUMNS} FROM preparation_resume_versions "
            "WHERE owner_id=%s AND opportunity_id=%s ORDER BY created_at DESC, id DESC",
            (owner_id, opportunity_id))

    def get_version(self, owner_id: str, opportunity_id: str, version_id: str):
        return self._one(
            f"SELECT {_VERSION_COLUMNS} FROM preparation_resume_versions "
            "WHERE owner_id=%s AND opportunity_id=%s AND id=%s",
            (owner_id, opportunity_id, version_id))

    def create_session(self, owner_id: str, opportunity_id: str, data: dict):
        payload = PreparationSessionInput.model_validate(data)
        prefix = "r-prep-" if payload.module == "resume" else "i-prep-"
        return self._one(
            f"""INSERT INTO preparation_sessions
                (thread_id,owner_id,module,opportunity_id,resume_version_id,
                 company,title,jd,resume_content,resume_label)
                SELECT %s,o.owner_id,%s,o.id,v.id,o.company,o.title,o.jd,v.content,v.label
                FROM preparation_opportunities o JOIN preparation_resume_versions v
                  ON v.owner_id=o.owner_id AND v.opportunity_id=o.id
                WHERE o.owner_id=%s AND o.id=%s AND v.id=%s RETURNING {_SESSION_COLUMNS}""",
            (prefix + str(uuid4()), payload.module, owner_id, opportunity_id, payload.resume_version_id))

    def get_session(self, owner_id: str, thread_id: str):
        return self._one(
            f"SELECT {_SESSION_COLUMNS} FROM preparation_sessions WHERE owner_id=%s AND thread_id=%s",
            (owner_id, thread_id))

    def delete_all_for_user(self, owner_id: str) -> None:
        with self.pool.connection() as conn:
            conn.execute("DELETE FROM preparation_opportunities WHERE owner_id=%s", (owner_id,))
