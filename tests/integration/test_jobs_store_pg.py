"""PG 集成测试：jobs 表指纹去重入库 + 关键词召回（search_jobs 缓存层）。

缺 POSTGRES_TEST_DSN 跳过；拒绝指向生产库 careercrew。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

DSN = os.environ.get("POSTGRES_TEST_DSN", "").strip()

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not DSN, reason="POSTGRES_TEST_DSN not set"),
]


def _require_disposable_db(dsn: str) -> None:
    dbname = urlparse(dsn.replace("postgresql://", "postgres://")).path.lstrip("/")
    if dbname == "careercrew":
        raise RuntimeError(
            "POSTGRES_TEST_DSN 指向生产库 careercrew，拒绝运行。请使用一次性测试库。"
        )


@pytest.fixture
def store():
    _require_disposable_db(DSN)
    from careercrew_core.jobs import PostgresJobsStore

    st = PostgresJobsStore(DSN)
    yield st
    with st._borrow() as conn, conn.transaction():
        conn.execute("DELETE FROM jobs")


def _job(title: str, company: str = "字节", city: str = "广州") -> dict:
    return {
        "title": title, "company": company, "city": city, "salary": "20-30k",
        "experience": "1-3年", "raw": f"{title} JD：负责核心业务", "source": "mcp-jobs",
    }


def test_upsert_dedup_and_keyword_merge(store) -> None:
    assert store.upsert([_job("大模型应用工程师")], "大模型") == 1
    # 同岗再来：主键冲突走 UPDATE，不新增行
    assert store.upsert([_job("大模型应用工程师", city="广州")], "LLM") == 1
    hits = store.search("大模型")
    assert len(hits) == 1
    row = hits[0]
    assert row["title"] == "大模型应用工程师"
    assert set(row["keywords"]) >= {"大模型", "LLM"}


def test_search_recall_paths(store) -> None:
    store.upsert([
        _job("Java 后端开发"),
        _job("数据分析专员", company="腾讯"),
        _job("大模型应用工程师"),
    ], "校招")
    store.upsert([_job("算法实习生")], "大模型")

    assert len(store.search("java")) == 1  # title ILIKE 大小写无关
    assert len(store.search("腾讯")) == 1  # company 命中
    titles = [h["title"] for h in store.search("大模型")]
    assert titles == ["大模型应用工程师"]


def test_teacher_query_requires_profession_and_city(store) -> None:
    store.upsert([
        _job("小学数学教师", company="广州实验小学", city="广州·天河区"),
        _job("小学英语老师", company="广州双语学校", city="广州·番禺区"),
        _job("Java 开发实习生", company="科技公司", city="广州·天河区"),
        _job("小学数学教师", company="深圳实验小学", city="深圳·南山区"),
    ], "混合岗位")

    hits = store.search("小学数学教师 广州")
    assert hits[0]["title"] == "小学数学教师"
    assert all("Java" not in row["title"] for row in hits)
    assert all(row["city"].startswith("广州") for row in hits)


def test_location_only_match_is_not_a_cache_hit(store) -> None:
    store.upsert([_job("Java 开发实习生", city="广州")], "Java 广州")
    assert store.search("小学数学教师 广州") == []


def test_teacher_alias_and_exact_match_ranking(store) -> None:
    store.upsert([
        _job("小学英语教师", city="广州"),
        _job("高中数学教师", city="广州"),
        _job("小学数学老师", city="广州"),
    ], "教师 广州")
    hits = store.search("小学数学教师 广州")
    assert hits[0]["title"] == "小学数学老师"
    assert hits[0]["matched_core_terms"] == ["小学", "数学", "教师"]


def test_freshness_window_excludes_stale(store) -> None:
    store.upsert([_job("很旧的岗位")], "老词")
    # 手动把 crawled_at 拨到 30 天前
    with store._borrow() as conn:
        conn.execute("UPDATE jobs SET crawled_at = now() - interval '30 days'")
        conn.commit()
    assert store.search("很旧", max_age_days=7) == []
    assert len(store.search("很旧", max_age_days=60)) == 1
