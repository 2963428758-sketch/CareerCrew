"""岗位库（jobs 表）：查询与采集解耦的数据层。

背景：search_jobs 每次调用都 spawn MCP 子进程爬取（1~2 分钟）。引入本地岗位库后，
查询路径优先读库（新鲜窗口内命中直接返回）；采集器负责把爬取结果按指纹去重入库。

指纹：mcp-jobs 返回无 URL，以 source|title|company|city 的 sha1 为稳定主键；
后续 patchright/CDP 后端有真实 URL 时写入 url 列并以 url 作指纹。
"""
from __future__ import annotations

import hashlib
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import UTC, datetime

_DEFAULT_MAX_AGE_DAYS = 7.0


def job_fingerprint(source: str, title: str, company: str, city: str) -> str:
    """稳定去重键：同一岗位多次采集命中同一条。"""
    raw = f"{source}|{title.strip()}|{company.strip()}|{city.strip()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:32]


class JobsStore(ABC):
    """岗位库契约。"""

    @abstractmethod
    def upsert(self, jobs: list[dict], keyword: str) -> int:
        """按指纹去重写入/刷新一批岗位，返回涉及条数。"""

    @abstractmethod
    def search(self, keyword: str, top_k: int = 8, max_age_days: float = _DEFAULT_MAX_AGE_DAYS) -> list[dict]:
        """按关键词召回新鲜岗位（title/company/jd 模糊 + keywords 精确），新采集优先。"""


class FakeJobsStore(JobsStore):
    """内存实现（单测用）。rows: {fingerprint: row_dict}。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rows: dict[str, dict] = {}
        self.upsert_calls = 0

    def upsert(self, jobs: list[dict], keyword: str) -> int:
        with self._lock:
            self.upsert_calls += 1
            for j in jobs:
                fp = job_fingerprint(
                    j.get("source", ""), j.get("title", ""),
                    j.get("company", ""), j.get("city", ""),
                )
                existing = self._rows.get(fp)
                kws = set(existing["keywords"]) if existing else set()
                kws.add(keyword)
                row = {
                    "fingerprint": fp,
                    "url": j.get("url", "") or (existing or {}).get("url", ""),
                    "title": j.get("title", ""),
                    "company": j.get("company", ""),
                    "city": j.get("city", ""),
                    "salary": j.get("salary", ""),
                    "experience": j.get("experience", ""),
                    "jd": j.get("raw", "") or (existing or {}).get("jd", ""),
                    "keywords": sorted(kws),
                    "source": j.get("source", "mcp-jobs"),
                    "crawled_at": datetime.now(UTC).isoformat(),
                }
                self._rows[fp] = row
            return len(jobs)

    def search(self, keyword: str, top_k: int = 8, max_age_days: float = _DEFAULT_MAX_AGE_DAYS) -> list[dict]:
        kw = keyword.lower()
        with self._lock:
            hits = [
                r for r in self._rows.values()
                if kw in r["title"].lower()
                or kw in r["company"].lower()
                or kw in r["jd"].lower()
                or keyword in r["keywords"]
            ]
        hits.sort(key=lambda r: r["crawled_at"], reverse=True)
        return hits[:top_k]


class PostgresJobsStore(JobsStore):
    """Postgres 实现：连接从共享池借还；首次操作才建表。"""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._schema_ready = False
        self._tls = threading.local()

    @contextmanager
    def _borrow(self):
        from careercrew_core.pg_pool import get_shared_pool

        with get_shared_pool(self._dsn).connection() as conn:
            yield conn

    def _ensure_schema(self, conn) -> None:
        """幂等建表（DDL 由调用方的事务上下文提交）。"""
        conn.execute(
            "CREATE TABLE IF NOT EXISTS jobs ("
            "fingerprint TEXT PRIMARY KEY, "
            "url TEXT NOT NULL DEFAULT '', "
            "title TEXT NOT NULL, "
            "company TEXT NOT NULL DEFAULT '', "
            "city TEXT NOT NULL DEFAULT '', "
            "salary TEXT NOT NULL DEFAULT '', "
            "experience TEXT NOT NULL DEFAULT '', "
            "jd TEXT NOT NULL DEFAULT '', "
            "keywords TEXT[] NOT NULL DEFAULT '{}', "
            "source TEXT NOT NULL DEFAULT 'mcp-jobs', "
            "crawled_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_crawled ON jobs(crawled_at DESC)")

    def _prepare(self, conn) -> None:
        """首次使用时建表（独立小事务；幂等）。"""
        if self._schema_ready:
            return
        with conn.transaction():
            self._ensure_schema(conn)
        self._schema_ready = True

    def upsert(self, jobs: list[dict], keyword: str) -> int:
        with self._borrow() as conn:
            self._prepare(conn)
            with conn.transaction():
                for j in jobs:
                    title = (j.get("title") or "").strip()
                    if not title:
                        continue
                    fp = job_fingerprint(
                        j.get("source", "mcp-jobs"), title,
                        (j.get("company") or "").strip(), (j.get("city") or "").strip(),
                    )
                    conn.execute(
                        "INSERT INTO jobs (fingerprint, url, title, company, city, salary, "
                        "experience, jd, keywords, source, crawled_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::text[],%s,now()) "
                        "ON CONFLICT (fingerprint) DO UPDATE SET "
                        "salary=EXCLUDED.salary, jd=EXCLUDED.jd, "
                        "keywords=(SELECT array_agg(DISTINCT k) FROM unnest(jobs.keywords || EXCLUDED.keywords) AS k), "
                        "crawled_at=now()",
                        (
                            fp, j.get("url", ""), title,
                            (j.get("company") or "").strip(), (j.get("city") or "").strip(),
                            j.get("salary", ""), j.get("experience", ""),
                            j.get("raw", ""), [keyword], j.get("source", "mcp-jobs"),
                        ),
                    )
        return len(jobs)

    def search(self, keyword: str, top_k: int = 8, max_age_days: float = _DEFAULT_MAX_AGE_DAYS) -> list[dict]:
        like = f"%{keyword}%"
        with self._borrow() as conn:
            self._prepare(conn)
            rows = conn.execute(
                "SELECT fingerprint, url, title, company, city, salary, experience, jd, "
                "keywords, source, crawled_at FROM jobs "
                "WHERE crawled_at > now() - (%s * interval '1 day') "
                "AND (title ILIKE %s OR company ILIKE %s OR jd ILIKE %s OR %s = ANY(keywords)) "
                "ORDER BY crawled_at DESC LIMIT %s",
                (max_age_days, like, like, like, keyword, top_k),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["crawled_at"] = d["crawled_at"].isoformat() if hasattr(d["crawled_at"], "isoformat") else d["crawled_at"]
            out.append(d)
        return out


def create_jobs_store(settings):
    """按配置创建岗位库：backend=fake 用内存实现（测试），否则 Postgres（共享池）。"""
    backend = getattr(settings.vector_store, "backend", "")
    if backend == "fake":
        return FakeJobsStore()
    dsn = (getattr(settings.memory.postgres, "dsn", "") or "").strip()
    if not dsn:
        raise ValueError("jobs store 需要 memory.postgres.dsn（或 backend=fake）")
    return PostgresJobsStore(dsn)
