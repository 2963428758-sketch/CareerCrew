"""岗位库与 search_jobs 缓存策略单测：指纹去重 / 召回 / 库优先不爬取。"""
from __future__ import annotations

import json

from careercrew_core.jobs import FakeJobsStore, job_fingerprint


def _job(title: str, company: str = "字节", city: str = "广州", salary: str = "20-30k") -> dict:
    return {
        "title": title, "company": company, "city": city, "salary": salary,
        "experience": "1-3年", "raw": f"{title} JD 全文", "source": "mcp-jobs",
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
    assert [h["title"] for h in store.search("大模型")] == ["大模型应用工程师"]  # keywords 精确命中
    assert store.search("不存在方向") == []


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
