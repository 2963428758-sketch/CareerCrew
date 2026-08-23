"""岗位库（jobs 表）：查询与采集解耦的数据层。

背景：search_jobs 每次调用都 spawn MCP 子进程爬取（1~2 分钟）。引入本地岗位库后，
查询路径优先读库（新鲜窗口内命中直接返回）；采集器负责把爬取结果按指纹去重入库。

指纹：mcp-jobs 返回无 URL，以 source|title|company|city 的 sha1 为稳定主键；
后续 patchright/CDP 后端有真实 URL 时写入 url 列并以 url 作指纹。
"""
from __future__ import annotations

import hashlib
import re
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

_DEFAULT_MAX_AGE_DAYS = 7.0
_QUERY_PREFIXES = ("我想找", "想找", "帮我找", "我要找", "求职", "找")
_QUERY_SUFFIXES = ("工作", "岗位", "职位", "机会", "一下", "的", "相关")
_TEXT_ALIASES = (("老师", "教师"), ("教员", "教师"))
_LOCATION_NAMES = {
    "北京", "上海", "广州", "深圳", "天津", "重庆", "杭州", "南京", "苏州",
    "成都", "武汉", "西安", "长沙", "郑州", "青岛", "厦门", "福州", "合肥",
    "济南", "宁波", "东莞", "佛山", "珠海", "无锡", "常州", "昆明", "南宁",
    "海口", "贵阳", "南昌", "太原", "石家庄", "沈阳", "大连", "长春",
    "哈尔滨", "兰州", "西宁", "银川", "拉萨", "乌鲁木齐", "呼和浩特",
    "香港", "澳门",
}
# 用于拆开常见中文复合方向，例如“小学数学教师” -> 小学 / 数学 / 教师。
_CORE_HINTS = (
    "数据分析", "产品经理", "大模型", "软件测试", "小学", "初中", "高中",
    "幼儿", "学前", "数学", "语文", "英语", "物理", "化学", "生物", "地理",
    "历史", "音乐", "美术", "体育", "教师", "教育", "前端", "后端", "全栈",
    "算法", "运维", "测试", "开发", "工程师", "产品", "运营", "设计", "销售",
    "会计", "财务", "人事", "行政", "客服", "采购", "外贸", "医生", "护士",
    "律师", "翻译", "餐厅", "餐饮", "酒店", "咖啡", "服务员", "店员",
    "收银员", "保洁", "保安", "骑手", "配送", "仓库", "普工", "厨师",
    "兼职", "全职", "实习",
)
_GENERIC_CORE_TERMS = {"兼职", "全职", "实习", "开发", "工程师"}


@dataclass(frozen=True)
class JobSearchQuery:
    """岗位检索结构：职业词负责召回，地点词只负责过滤。"""

    core_terms: tuple[str, ...]
    location_terms: tuple[str, ...]


def _normalize_text(text: str) -> str:
    normalized = (text or "").strip().lower()
    for old, new in _TEXT_ALIASES:
        normalized = normalized.replace(old, new)
    return normalized


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def parse_job_search_query(keyword: str) -> JobSearchQuery:
    """解析自然语言岗位查询，地点永远不会被当成职业相关性命中。"""
    chunks = re.findall(r"[A-Za-z0-9+#.]+|[\u4e00-\u9fff]+", keyword or "")
    core_terms: list[str] = []
    location_terms: list[str] = []
    locations_by_length = sorted(_LOCATION_NAMES, key=len, reverse=True)
    for chunk in chunks:
        term = _normalize_text(chunk)
        for prefix in _QUERY_PREFIXES:
            if term.startswith(prefix):
                term = term[len(prefix):]
                break
        changed = True
        while changed and term:
            changed = False
            for suffix in _QUERY_SUFFIXES:
                if term.endswith(suffix) and len(term) > len(suffix):
                    term = term[:-len(suffix)]
                    changed = True
                    break
        if not term:
            continue

        location_candidate = term[1:] if term.startswith("在") else term
        if (
            location_candidate in _LOCATION_NAMES
            or location_candidate.endswith(("市", "区", "县"))
        ):
            _append_unique(location_terms, location_candidate.removesuffix("市"))
            continue

        # 兼容“广州或深圳”“广州小学教师”“教师在广州”等未加空格写法。
        found_locations = sorted(
            (
                location for location in locations_by_length
                if location in location_candidate
            ),
            key=lambda location: (location_candidate.index(location), -len(location)),
        )
        if found_locations:
            remainder = location_candidate
            for location in found_locations:
                _append_unique(location_terms, location)
                remainder = remainder.replace(location, "")
            term = re.sub(r"^(?:在|的|或|和|及|与)+|(?:在|的|或|和|及|与)+$", "", remainder)
        if not term:
            continue

        hints = [hint for hint in _CORE_HINTS if hint in term]
        if hints:
            for hint in hints:
                _append_unique(core_terms, hint)
        else:
            _append_unique(core_terms, term)
    return JobSearchQuery(tuple(core_terms), tuple(location_terms))


def _search_terms(keyword: str) -> list[str]:
    """兼容旧调用：返回职业词在前、地点词在后的扁平列表。"""
    query = parse_job_search_query(keyword)
    return [*query.core_terms, *query.location_terms]


def _job_match(row: dict, query: JobSearchQuery) -> tuple[int, list[str], list[str]]:
    """返回匹配分与命中词；0 表示不满足职业/地点硬条件。"""
    core_haystack = _normalize_text(" ".join((
        str(row.get("title") or ""),
        str(row.get("company") or ""),
        str(row.get("jd") or row.get("raw") or ""),
        str(row.get("experience") or ""),
    )))
    city_haystack = _normalize_text(str(row.get("city") or ""))
    matched_core = [term for term in query.core_terms if term in core_haystack]
    required_core = [
        term for term in query.core_terms if term not in _GENERIC_CORE_TERMS
    ] or list(query.core_terms)
    matched_required = [term for term in required_core if term in core_haystack]
    matched_locations = [
        term for term in query.location_terms if term in city_haystack
    ]
    if required_core and not matched_required:
        return 0, [], matched_locations
    if query.location_terms and not matched_locations:
        return 0, matched_core, []
    # 职业相关性权重大于地点；精确岗位会自然排在宽泛相关岗位前。
    score = len(matched_core) * 10 + len(matched_locations)
    return max(score, 1), matched_core, matched_locations


def rank_job_matches(
    jobs: list[dict], query: JobSearchQuery, top_k: int
) -> list[dict]:
    """缓存与实时平台共用的确定性过滤/排序，阻断跨职业脏结果。"""
    if not query.core_terms or top_k <= 0:
        return []
    scored: list[tuple[int, str, dict]] = []
    for row in jobs:
        score, matched_core, matched_locations = _job_match(row, query)
        if not score:
            continue
        enriched = dict(row)
        enriched["matched_core_terms"] = matched_core
        enriched["matched_location_terms"] = matched_locations
        scored.append((score, str(row.get("crawled_at") or ""), enriched))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [row for _, _, row in scored[:top_k]]


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
        query = parse_job_search_query(keyword)
        if not query.core_terms or top_k <= 0:
            return []
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        with self._lock:
            rows = [
                row for row in self._rows.values()
                if datetime.fromisoformat(row["crawled_at"]) > cutoff
            ]
        return rank_job_matches(rows, query, top_k)


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
        query = parse_job_search_query(keyword)
        if not query.core_terms or top_k <= 0:
            return []
        core_patterns = [f"%{term}%" for term in query.core_terms]
        required_core = [
            term for term in query.core_terms if term not in _GENERIC_CORE_TERMS
        ] or list(query.core_terms)
        required_patterns = [f"%{term}%" for term in required_core]
        location_patterns = [f"%{term}%" for term in query.location_terms]
        core_text = (
            "replace(replace(lower(concat_ws(' ', title, company, jd, experience)), "
            "'老师', '教师'), '教员', '教师')"
        )
        clauses = ["crawled_at > now() - (%s * interval '1 day')"]
        params: list = [max_age_days]
        if required_patterns:
            clauses.append("(" + " OR ".join(f"{core_text} LIKE %s" for _ in required_patterns) + ")")
            params.extend(required_patterns)
        if location_patterns:
            clauses.append("(" + " OR ".join("lower(city) LIKE %s" for _ in location_patterns) + ")")
            params.extend(location_patterns)
        score_parts = [
            f"CASE WHEN {core_text} LIKE %s THEN 10 ELSE 0 END"
            for _ in core_patterns
        ]
        score_params: list = list(core_patterns)
        score_parts.extend(
            "CASE WHEN lower(city) LIKE %s THEN 1 ELSE 0 END"
            for _ in location_patterns
        )
        score_params.extend(location_patterns)
        score_sql = " + ".join(score_parts) or "0"
        with self._borrow() as conn:
            self._prepare(conn)
            rows = conn.execute(
                "SELECT fingerprint, url, title, company, city, salary, experience, jd, "
                "keywords, source, crawled_at FROM jobs "
                f"WHERE {' AND '.join(clauses)} "
                f"ORDER BY ({score_sql}) DESC, crawled_at DESC LIMIT %s",
                (*params, *score_params, max(top_k * 4, top_k)),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["crawled_at"] = d["crawled_at"].isoformat() if hasattr(d["crawled_at"], "isoformat") else d["crawled_at"]
            out.append(d)
        return rank_job_matches(out, query, top_k)


def create_jobs_store(settings):
    """按配置创建岗位库：backend=fake 用内存实现（测试），否则 Postgres（共享池）。"""
    backend = getattr(settings.vector_store, "backend", "")
    if backend == "fake":
        return FakeJobsStore()
    dsn = (getattr(settings.memory.postgres, "dsn", "") or "").strip()
    if not dsn:
        raise ValueError("jobs store 需要 memory.postgres.dsn（或 backend=fake）")
    return PostgresJobsStore(dsn)
