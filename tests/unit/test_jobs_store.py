"""岗位库与 search_jobs 缓存策略单测：指纹去重 / 召回 / 库优先不爬取。"""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from careercrew_core.jobs import FakeJobsStore, PostgresJobsStore, job_fingerprint
from careercrew_core.jobs.store import parse_job_search_query


def _job(title: str, company: str = "字节", city: str = "广州", salary: str = "20-30k") -> dict:
    return {
        "title": title, "company": company, "city": city, "salary": salary,
        "experience": "1-3年", "raw": f"{title} JD 全文", "source": "liepin",
        "url": "https://www.liepin.com/job/1",
    }


def test_fingerprint_stable_and_distinct() -> None:
    a = job_fingerprint("mcp-jobs", "Java 开发", "字节", "广州")
    b = job_fingerprint("mcp-jobs", "Java 开发 ", " 字节", "广州")
    assert a == b  # 空白不影响
    c = job_fingerprint("mcp-jobs", "Java 开发", "腾讯", "广州")
    assert a != c


def test_upsert_dedup_merges_keywords() -> None:
    store = FakeJobsStore()
    assert store.upsert([_job("大模型应用工程师")], "大模型") == 1
    # 同一岗位换个搜索词再来：不新增行，关键词合并
    assert store.upsert([_job("大模型应用工程师")], "LLM") == 1
    hits = store.search("大模型")
    assert len(hits) == 1
    assert set(hits[0]["keywords"]) == {"大模型", "LLM"}


def test_search_recall_by_title_and_keyword() -> None:
    store = FakeJobsStore()
    store.upsert([_job("Java 后端开发"), _job("数据分析专员", company="腾讯")], "校招")
    store.upsert([_job("大模型应用工程师")], "大模型")

    assert len(store.search("java")) == 1  # title 模糊（大小写无关）
    assert [h["title"] for h in store.search("大模型")] == ["大模型应用工程师"]
    assert store.search("不存在方向") == []


@pytest.mark.parametrize(
    ("text", "core", "locations"),
    [
        ("小学数学教师 广州", ("小学", "数学", "教师"), ("广州",)),
        ("数学老师 广州", ("数学", "教师"), ("广州",)),
        ("我想找教师相关的工作,在广州", ("教师",), ("广州",)),
        ("广州小学数学教师", ("小学", "数学", "教师"), ("广州",)),
        ("广州 Java 实习", ("java", "实习"), ("广州",)),
        ("深圳 前端开发", ("前端", "开发"), ("深圳",)),
        ("有教师资格证 广州或深圳", ("教师",), ("广州", "深圳")),
        ("兼职 餐厅服务员 深圳", ("兼职", "餐厅", "服务员"), ("深圳",)),
        ("我想找深圳的酒店服务员工作", ("酒店", "服务员"), ("深圳",)),
    ],
)
def test_parse_job_search_query_separates_core_and_location(
    text, core, locations
) -> None:
    query = parse_job_search_query(text)
    assert query.core_terms == core
    assert query.location_terms == locations


def test_search_reuses_cache_when_query_order_or_fillers_change() -> None:
    store = FakeJobsStore()
    store.upsert([_job("Java 开发实习生", city="广州·天河区")], "Java 实习 广州")
    store.upsert([_job("数据分析实习生", company="腾讯", city="广州")], "数据分析")

    hits = store.search("我想找广州的 Java 实习工作")
    assert hits[0]["title"] == "Java 开发实习生"
    assert hits[0]["city"] == "广州·天河区"


def test_teacher_query_excludes_java_and_wrong_city() -> None:
    store = FakeJobsStore()
    store.upsert([
        _job("小学数学教师", company="广州实验小学", city="广州·天河区"),
        _job("小学英语老师", company="广州双语学校", city="广州·番禺区"),
        _job("Java 开发实习生", company="科技公司", city="广州·天河区"),
        _job("小学数学教师", company="深圳实验小学", city="深圳·南山区"),
    ], "混合岗位")

    hits = store.search("小学数学教师 广州")
    titles_and_cities = [(row["title"], row["city"]) for row in hits]
    assert titles_and_cities[0] == ("小学数学教师", "广州·天河区")
    assert all("Java" not in title for title, _ in titles_and_cities)
    assert all(city.startswith("广州") for _, city in titles_and_cities)


def test_location_alone_cannot_make_unrelated_cache_hit() -> None:
    store = FakeJobsStore()
    store.upsert([_job("Java 开发实习生", city="广州·天河区")], "Java 广州")

    assert store.search("小学数学教师 广州") == []


def test_teacher_alias_matches_teacher_title() -> None:
    store = FakeJobsStore()
    store.upsert([_job("小学数学老师", city="广州")], "小学数学老师 广州")

    hits = store.search("小学数学教师 广州")
    assert [row["title"] for row in hits] == ["小学数学老师"]
    assert hits[0]["matched_core_terms"] == ["小学", "数学", "教师"]


def test_exact_teacher_match_ranks_above_partial_teacher_match() -> None:
    store = FakeJobsStore()
    store.upsert([
        _job("小学英语教师", city="广州"),
        _job("高中数学教师", city="广州"),
        _job("小学数学教师", city="广州"),
    ], "教师 广州")

    hits = store.search("小学数学教师 广州")
    assert hits[0]["title"] == "小学数学教师"
    assert len(hits[0]["matched_core_terms"]) == 3


@pytest.mark.parametrize("query", ["", "广州", "我想找广州的工作"])
def test_missing_profession_does_not_return_all_city_jobs(query) -> None:
    store = FakeJobsStore()
    store.upsert([_job("Java 开发", city="广州")], "Java 广州")
    assert store.search(query) == []


def test_java_query_excludes_other_internships_in_same_city() -> None:
    store = FakeJobsStore()
    store.upsert([
        _job("Java 开发实习生", city="广州"),
        _job("数据分析实习生", city="广州"),
        _job("Java 开发实习生", city="深圳"),
    ], "混合实习")
    hits = store.search("广州 Java 实习")
    assert [row["title"] for row in hits] == ["Java 开发实习生"]
    assert hits[0]["city"] == "广州"


def test_waiter_query_requires_job_type_not_only_part_time() -> None:
    store = FakeJobsStore()
    store.upsert([
        _job("兼职餐厅服务员", company="麦当劳", city="深圳·福田区"),
        _job("兼职小学助教", company="培训机构", city="深圳·南山区"),
        _job("餐厅服务员", company="广州餐厅", city="广州"),
    ], "混合兼职")

    hits = store.search("兼职 餐厅服务员 深圳")
    assert [row["title"] for row in hits] == ["兼职餐厅服务员"]
    assert hits[0]["matched_core_terms"] == ["兼职", "餐厅", "服务员"]


def test_waiter_query_can_recall_broader_waiter_title() -> None:
    store = FakeJobsStore()
    store.upsert([
        _job("餐饮门店服务员兼职", company="餐饮公司", city="深圳"),
    ], "服务员 深圳")

    assert store.search("餐厅服务员 兼职 深圳")[0]["title"] == "餐饮门店服务员兼职"


def test_fake_store_honors_freshness_window() -> None:
    store = FakeJobsStore()
    store.upsert([_job("小学数学教师", city="广州")], "教师 广州")
    row = next(iter(store._rows.values()))
    row["crawled_at"] = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    assert store.search("教师 广州", max_age_days=7) == []
    assert len(store.search("教师 广州", max_age_days=60)) == 1


def test_postgres_search_uses_core_and_city_then_defense_filters(monkeypatch) -> None:
    class Result:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class Connection:
        def __init__(self):
            self.sql = ""
            self.params = ()

        def execute(self, sql, params):
            self.sql = sql
            self.params = params
            now = datetime.now(UTC)
            return Result([
                {**_job("Java 开发实习生", city="广州"), "jd": "", "keywords": [],
                 "fingerprint": "java", "crawled_at": now},
                {**_job("小学数学老师", city="广州"), "jd": "", "keywords": [],
                 "fingerprint": "teacher", "crawled_at": now},
            ])

    conn = Connection()

    @contextmanager
    def borrow():
        yield conn

    store = PostgresJobsStore("postgresql://unused")
    store._schema_ready = True
    monkeypatch.setattr(store, "_borrow", borrow)
    hits = store.search("小学数学教师 广州")
    assert [row["title"] for row in hits] == ["小学数学老师"]
    assert "lower(city) LIKE" in conn.sql
    assert "array_to_string" not in conn.sql
    assert "%教师%" in conn.params and "%广州%" in conn.params


def test_make_search_jobs_tool_cache_hit_skips_crawl(monkeypatch) -> None:
    """库内新鲜命中时绝不触发 MCP 子进程。"""
    import importlib

    sj = importlib.import_module("careercrew_core.tools.internal.search_jobs")

    def boom(*a, **kw):
        raise AssertionError("cache hit 不应调用 MCP 爬取")

    monkeypatch.setattr(sj, "search_jobs_mcp", boom)

    store = FakeJobsStore()
    store.upsert([_job("大模型应用工程师")], "大模型")
    tool = sj.make_search_jobs_tool(store)
    out = json.loads(tool.invoke({"direction": "大模型", "top_k": 5}))
    assert out[0]["title"] == "大模型应用工程师"
    assert out[0]["company"] == "字节"
    assert out[0]["source"] == "liepin"
    assert out[0]["source_label"] == "猎聘"
    assert out[0]["retrieval_mode"] == "cache"
    assert out[0]["retrieval_mode_label"] == "近期缓存"


def test_make_search_jobs_tool_miss_crawls_and_persists(monkeypatch) -> None:
    import importlib

    sj = importlib.import_module("careercrew_core.tools.internal.search_jobs")

    monkeypatch.setattr(
        sj, "search_jobs_mcp",
        lambda keyword, city="", top_k=10, timeout=180.0: [_job("数据分析师")],
    )

    store = FakeJobsStore()
    tool = sj.make_search_jobs_tool(store)
    out = json.loads(tool.invoke({"direction": "数据分析", "top_k": 5}))
    assert out[0]["title"] == "数据分析师"
    assert out[0]["company"] == "字节"
    assert out[0]["source_label"] == "猎聘"
    assert out[0]["retrieval_mode"] == "live"
    # 已入库：再次查询走缓存路径
    assert len(store.search("数据分析")) == 1
    assert store.upsert_calls == 1


def test_make_search_jobs_tool_crawl_failure_returns_error(monkeypatch) -> None:
    import importlib

    sj = importlib.import_module("careercrew_core.tools.internal.search_jobs")

    def boom(keyword, city="", top_k=10, timeout=180.0):
        raise TimeoutError("crawl hang")

    monkeypatch.setattr(sj, "search_jobs_mcp", boom)

    tool = sj.make_search_jobs_tool(FakeJobsStore())
    out = json.loads(tool.invoke({"direction": "测试", "top_k": 3}))
    assert "error" in out[0]


def test_make_search_jobs_tool_none_store_keeps_direct_behavior(monkeypatch) -> None:
    """store=None 保持旧行为：直连 MCP、不入库。"""
    import importlib

    sj = importlib.import_module("careercrew_core.tools.internal.search_jobs")

    calls = []
    monkeypatch.setattr(
        sj, "search_jobs_mcp",
        lambda keyword, city="", top_k=10, timeout=180.0: calls.append(keyword) or [_job("前端工程师")],
    )

    tool = sj.make_search_jobs_tool(None)
    out = json.loads(tool.invoke({"direction": "前端", "top_k": 3}))
    assert out[0]["title"] == "前端工程师"
    assert calls == ["前端"]


def test_search_jobs_does_not_invent_missing_company(monkeypatch) -> None:
    import importlib

    sj = importlib.import_module("careercrew_core.tools.internal.search_jobs")
    missing_company = _job("Java 实习生", company="", city="广州·天河区")
    monkeypatch.setattr(
        sj,
        "search_jobs_mcp",
        lambda keyword, city="", top_k=10, timeout=180.0: [missing_company],
    )

    tool = sj.make_search_jobs_tool(None)
    out = json.loads(tool.invoke({"direction": "广州 Java 实习", "top_k": 3}))
    assert out[0]["company"] == "公司名称未提供"
    assert out[0]["city"] == "广州·天河区"


def test_unrelated_city_cache_falls_through_to_live_teacher_search(monkeypatch) -> None:
    import importlib

    sj = importlib.import_module("careercrew_core.tools.internal.search_jobs")
    calls: list[str] = []
    store = FakeJobsStore()
    store.upsert([_job("Java 开发实习生", city="广州")], "Java 广州")
    monkeypatch.setattr(
        sj,
        "search_jobs_mcp",
        lambda keyword, city="", top_k=10, timeout=180.0: calls.append(keyword) or [
            _job("小学数学教师", company="广州实验小学", city="广州")
        ],
    )

    tool = sj.make_search_jobs_tool(store)
    out = json.loads(tool.invoke({"direction": "小学数学教师 广州", "top_k": 5}))
    assert calls == ["小学数学教师 广州"]
    assert [row["title"] for row in out] == ["小学数学教师"]
    assert out[0]["retrieval_mode"] == "live"


def test_live_results_filter_out_cross_profession_and_wrong_city(monkeypatch) -> None:
    import importlib

    sj = importlib.import_module("careercrew_core.tools.internal.search_jobs")
    monkeypatch.setattr(
        sj,
        "search_jobs_mcp",
        lambda keyword, city="", top_k=10, timeout=180.0: [
            _job("Java 开发实习生", city="广州"),
            _job("小学数学老师", company="广州实验小学", city="广州"),
            _job("小学数学教师", company="深圳实验小学", city="深圳"),
        ],
    )

    tool = sj.make_search_jobs_tool(None)
    out = json.loads(tool.invoke({"direction": "小学数学教师 广州", "top_k": 5}))
    assert [row["title"] for row in out] == ["小学数学老师"]
    assert out[0]["matched_core_terms"] == ["小学", "数学", "教师"]
    assert out[0]["matched_location_terms"] == ["广州"]


def test_live_only_unrelated_results_returns_no_match_error(monkeypatch) -> None:
    import importlib

    sj = importlib.import_module("careercrew_core.tools.internal.search_jobs")
    monkeypatch.setattr(
        sj,
        "search_jobs_mcp",
        lambda keyword, city="", top_k=10, timeout=180.0: [
            _job("Java 开发实习生", city="广州")
        ],
    )
    tool = sj.make_search_jobs_tool(None)
    out = json.loads(tool.invoke({"direction": "小学数学教师 广州", "top_k": 5}))
    assert "error" in out[0]
    assert "未找到" in out[0]["error"]


def test_liepin_live_search_has_bounded_timeout(monkeypatch) -> None:
    import importlib

    sj = importlib.import_module("careercrew_core.tools.internal.search_jobs")
    seen: dict[str, float] = {}

    def fake_search(keyword, city="", top_k=10, timeout=180.0):
        seen["timeout"] = timeout
        return [_job("小学数学教师", city="广州")]

    monkeypatch.setattr(sj, "search_jobs_mcp", fake_search)
    tool = sj.make_search_jobs_tool(None)
    out = json.loads(tool.invoke({"direction": "小学数学教师 广州", "top_k": 5}))
    assert out[0]["title"] == "小学数学教师"
    assert seen["timeout"] == sj._LIEPIN_TIMEOUT_SECONDS == 25.0


def test_search_jobs_realtime_bypasses_cache(monkeypatch) -> None:
    import importlib
    sj = importlib.import_module("careercrew_core.tools.internal.search_jobs")
    store = FakeJobsStore()
    store.upsert([_job("Java 开发实习生 (旧缓存)", city="广州")], "Java 广州")

    live_called = []
    def fake_live(keyword, city="", top_k=10, timeout=180.0):
        live_called.append(keyword)
        return [_job("Java 大模型工程师 (最新实时)", city="广州")]

    monkeypatch.setattr(sj, "search_jobs_mcp", fake_live)

    # 1. 默认常规搜索：命中 7 天缓存，不调实时
    tool = sj.make_search_jobs_tool(store)
    out_cached = json.loads(tool.invoke({"direction": "Java 广州", "top_k": 5}))
    assert len(live_called) == 0
    assert out_cached[0]["retrieval_mode"] == "cache"
    assert "旧缓存" in out_cached[0]["title"]

    # 2. 传参 realtime=True：强制穿透缓存，调实时
    out_realtime = json.loads(tool.invoke({"direction": "Java 广州", "top_k": 5, "realtime": True}))
    assert len(live_called) == 1
    assert out_realtime[0]["retrieval_mode"] == "live"
    assert "最新实时" in out_realtime[0]["title"]

    # 3. 意图关键词触发：包含“实时抓取”等，自动穿透缓存
    out_keyword = json.loads(tool.invoke({"direction": "帮我实时抓取一下 广州 Java 岗位", "top_k": 5}))
    assert len(live_called) == 2
    assert out_keyword[0]["retrieval_mode"] == "live"

