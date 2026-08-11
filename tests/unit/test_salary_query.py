"""salary_query 工具单元测试（假数据源，不触发浏览器）。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from careercrew_core.tools.internal.salary_query import (
    aggregate_salaries,
    make_salary_query_tool,
)


def _fake_jobs() -> list[dict]:
    return [
        {
            "title": "大模型算法工程师",
            "city": "北京-海淀区",
            "salary": "30-60k",
            "salary_k": {"min_k": 30.0, "max_k": 60.0, "months": None},
            "experience": "3-5年",
        },
        {
            "title": "大模型研发工程师",
            "city": "北京",
            "salary": "40-70k·15薪",
            "salary_k": {"min_k": 40.0, "max_k": 70.0, "months": 15},
            "experience": "4年",
        },
        {
            "title": "电话客服",
            "city": "重庆-南岸区",
            "salary": "5-9k",
            "salary_k": {"min_k": 5.0, "max_k": 9.0, "months": None},
            "experience": "不限",
        },
        {
            "title": "大模型工程师（上海）",
            "city": "上海",
            "salary": "1.5-2.5万",
            "salary_k": {"min_k": 15.0, "max_k": 25.0, "months": None},
            "experience": "1-3年",
        },
    ]


def _fake_search(*args, **kwargs) -> list[dict]:
    return _fake_jobs()


def test_aggregate_salaries() -> None:
    agg = aggregate_salaries(_fake_jobs())
    assert agg["sample_count"] == 4
    assert agg["total_count"] == 4
    assert agg["monthly_k"] == {"min": 5.0, "max": 70.0, "median": 32.5}
    # 只有带薪数样本参与年薪估算
    assert agg["annual_k"] == {"min": 600.0, "max": 1050.0, "samples": 1}


def test_aggregate_salaries_empty() -> None:
    assert aggregate_salaries([])["sample_count"] == 0


def test_salary_query_filters_noise_and_aggregates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "careercrew_core.tools.internal.salary_query.search_jobs_mcp", _fake_search
    )
    tool = make_salary_query_tool()
    out = json.loads(tool.invoke({"direction": "大模型", "company": "某公司", "top_k": 8}))
    assert out["source"] == "liepin(猎聘实时JD)"
    assert out["sample_count"] == 3  # 电话客服被噪音过滤
    assert out["monthly_k"]["median"] == 45.0  # midpoints: 45 / 55 / 20
    assert len(out["samples"]) == 3
    assert all("大模型" in s["title"] for s in out["samples"])


def test_salary_query_compound_direction_matches_role_titles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # "大模型工程师" 应命中 "大模型算法工程师" 等真实标题（去掉通用后缀匹配词头）
    monkeypatch.setattr(
        "careercrew_core.tools.internal.salary_query.search_jobs_mcp", _fake_search
    )
    tool = make_salary_query_tool()
    out = json.loads(tool.invoke({"direction": "大模型工程师", "top_k": 8}))
    assert out["sample_count"] == 3
    assert all("大模型" in s["title"] for s in out["samples"])


def test_salary_query_city_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "careercrew_core.tools.internal.salary_query.search_jobs_mcp", _fake_search
    )
    tool = make_salary_query_tool()
    out = json.loads(tool.invoke({"direction": "大模型", "city": "北京", "top_k": 8}))
    assert out["sample_count"] == 2  # 上海样本被过滤
    assert all("北京" in s["city"] for s in out["samples"])


def test_salary_query_call_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "careercrew_core.tools.internal.salary_query.search_jobs_mcp", _fake_search
    )
    tool = make_salary_query_tool(max_calls=2)
    tool.invoke({"direction": "大模型", "top_k": 8})
    tool.invoke({"direction": "大模型", "top_k": 8})
    third = json.loads(tool.invoke({"direction": "大模型", "top_k": 8}))
    assert "调用上限" in third["error"]


def test_salary_query_empty_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "careercrew_core.tools.internal.salary_query.search_jobs_mcp",
        lambda *a, **k: [],
    )
    out = json.loads(make_salary_query_tool().invoke({"direction": "不存在方向", "top_k": 8}))
    assert "未找到" in out["error"]


def test_salary_query_source_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("浏览器不可用")

    monkeypatch.setattr(
        "careercrew_core.tools.internal.salary_query.search_jobs_mcp", boom
    )
    out = json.loads(make_salary_query_tool().invoke({"direction": "大模型", "top_k": 8}))
    assert "暂时不可用" in out["error"]


def test_make_tools_registers_salary_query_for_salary_and_planner() -> None:
    from careercrew_api.runtime import CareerCrewRuntime

    fake = SimpleNamespace(episodic=None, multimodal_search=object(), user_model=object())
    for kind in ("salary", "planner"):
        reg = CareerCrewRuntime._make_tools(fake, kind)
        assert reg.has("salary_query")
