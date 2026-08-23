"""mcp-jobs 解析与薪资解析单元测试（salary_query 前置能力）。"""
from __future__ import annotations

from careercrew_core.tools.jobs.mcp_jobs import (
    _parse_content,
    _parse_response,
    parse_salary_range,
)


def test_parse_salary_range_k_formats() -> None:
    assert parse_salary_range("20-35k") == {"min_k": 20.0, "max_k": 35.0, "months": None}
    assert parse_salary_range("30-60K") == {"min_k": 30.0, "max_k": 60.0, "months": None}
    assert parse_salary_range("20~35k") == {"min_k": 20.0, "max_k": 35.0, "months": None}


def test_parse_salary_range_with_months() -> None:
    assert parse_salary_range("40-70k·15薪") == {"min_k": 40.0, "max_k": 70.0, "months": 15}
    assert parse_salary_range("65-95k·15薪") == {"min_k": 65.0, "max_k": 95.0, "months": 15}


def test_parse_salary_range_wan_unit() -> None:
    assert parse_salary_range("1.5-2.5万") == {"min_k": 15.0, "max_k": 25.0, "months": None}
    assert parse_salary_range("1-2万") == {"min_k": 10.0, "max_k": 20.0, "months": None}


def test_parse_salary_range_invalid_or_face_to_face() -> None:
    assert parse_salary_range("面议") is None
    assert parse_salary_range("薪资面议") is None
    assert parse_salary_range("") is None
    assert parse_salary_range("无") is None


def test_parse_content_extracts_salary_with_months() -> None:
    job = _parse_content(
        "大模型研发工程师（北京）【北京-海淀区】40-70k·15薪4年以上硕士DJI 大疆智能硬件"
    )
    assert job["salary"] == "40-70K·15薪"
    assert job["salary_k"] == {"min_k": 40.0, "max_k": 70.0, "months": 15}


def test_parse_response_prefers_structured_fields() -> None:
    text = (
        '{"jobs": ['
        '{"title": "大模型工程师", "salary": "30-50k", "company": "某公司", '
        '"address": "北京", "tags": ["1-3年", "本科"], '
        '"jobDetail": "/a/123.html"},'
        '{"content": "电话客服【重庆-南岸区】5-9k经验不限重庆某公司"}'
        "]}"
    )
    jobs = _parse_response(text, 10)
    assert jobs[0]["title"] == "大模型工程师"
    assert jobs[0]["salary"] == "30-50k"
    assert jobs[0]["company"] == "某公司"
    assert jobs[0]["experience"] == "1-3年"
    assert jobs[0]["url"] == "https://www.liepin.com/a/123.html"
    assert jobs[0]["source"] == "liepin"
    assert jobs[0]["salary_k"] == {"min_k": 30.0, "max_k": 50.0, "months": None}
    assert jobs[1]["title"] == "电话客服"
    assert jobs[1]["company"] == ""
    assert jobs[1]["salary_k"] == {"min_k": 5.0, "max_k": 9.0, "months": None}
