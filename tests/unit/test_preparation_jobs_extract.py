"""search_jobs 结构化结果提取：只信任服务端结构化返回，不解析 LLM Markdown。"""
from dataclasses import dataclass, field

from careercrew_core.preparation.jobs_extract import (
    MAX_JOBS,
    extract_jobs_from_agent_result,
)


@dataclass
class Iter:
    tool_calls: list = field(default_factory=list)
    tool_results: list = field(default_factory=list)
    tool_results_named: list = field(default_factory=list)


@dataclass
class Result:
    iterations: list = field(default_factory=list)


def named(name, content, artifact=None, tool_call_id="c1"):
    return {"name": name, "tool_call_id": tool_call_id, "content": content,
            "artifact": artifact}


def job(company="测试公司", title="Java开发", city="深圳", salary="20-30K",
        source="boss", url="https://example.com/j/1", jd="负责接口开发"):
    return {"company": company, "title": title, "city": city, "salary": salary,
            "source": source, "source_label": "Boss直聘", "url": url, "jd": jd}


def test_named_artifact_jobs_extracted_and_normalized():
    result = Result(iterations=[Iter(
        tool_calls=[{"name": "search_jobs", "id": "c1"}],
        tool_results_named=[named("search_jobs", "[]", artifact=[job()])],
    )])
    jobs = extract_jobs_from_agent_result(result)
    assert len(jobs) == 1
    assert jobs[0]["company"] == "测试公司"
    assert jobs[0]["title"] == "Java开发"
    assert jobs[0]["url"] == "https://example.com/j/1"


def test_named_json_content_parsed_when_artifact_missing():
    import json

    result = Result(iterations=[Iter(
        tool_results_named=[named("search_jobs", json.dumps([job()], ensure_ascii=False))],
    )])
    jobs = extract_jobs_from_agent_result(result)
    assert len(jobs) == 1 and jobs[0]["company"] == "测试公司"


def test_error_results_and_other_tools_excluded():
    result = Result(iterations=[Iter(
        tool_results_named=[
            named("search_jobs", '[{"error": "渠道不可用"}]', artifact=[{"error": "x"}]),
            named("rag_query", '[{"company": "RAG", "title": "x"}]', artifact=[job()]),
            named("memory_search", "纯文本记忆结果"),
        ],
    )])
    assert extract_jobs_from_agent_result(result) == []


def test_malformed_json_content_skipped():
    result = Result(iterations=[Iter(
        tool_results_named=[named("search_jobs", "这不是JSON[截断")],
    )])
    assert extract_jobs_from_agent_result(result) == []


def test_dedup_by_source_url_then_identity():
    result = Result(iterations=[Iter(tool_results_named=[named(
        "search_jobs", "", artifact=[
            job(),
            job(),  # 完全相同 → 去重
            job(url="", company="另一家"),  # 无 url 按 (source, company, title, city) 判重
            job(url="", company="另一家"),
        ])])])
    jobs = extract_jobs_from_agent_result(result)
    assert len(jobs) == 2


def test_caps_jobs_and_jd_length():
    many = [job(company=f"公司{i}", url=f"https://example.com/j/{i}") for i in range(30)]
    long_jd = job(jd="长" * 40000, url="https://example.com/j/long")
    result = Result(iterations=[Iter(tool_results_named=[named(
        "search_jobs", "", artifact=[long_jd] + many)])])
    jobs = extract_jobs_from_agent_result(result)
    assert len(jobs) == MAX_JOBS
    by_url = {j["url"]: j for j in jobs}
    assert len(by_url["https://example.com/j/long"]["jd"]) == 30000


def test_unsafe_url_neutralized_not_dropped():
    result = Result(iterations=[Iter(tool_results_named=[named(
        "search_jobs", "", artifact=[
            job(company="A公司", url="javascript:alert(1)"),
            job(company="B公司", url=""),
        ])])])
    jobs = extract_jobs_from_agent_result(result)
    assert [j["url"] for j in jobs] == ["", ""]


def test_blank_company_or_title_skipped():
    result = Result(iterations=[Iter(tool_results_named=[named(
        "search_jobs", "", artifact=[job(company="  "), job(title="")])])])
    assert extract_jobs_from_agent_result(result) == []


def test_legacy_positional_fallback_when_no_named_records():
    import json

    result = Result(iterations=[
        Iter(tool_calls=[{"name": "search_jobs", "id": "c1"}],
             tool_results=[json.dumps([job()], ensure_ascii=False)]),
        Iter(tool_calls=[{"name": "rag_query", "id": "c2"}],
             tool_results=['[{"company": "不该出现", "title": "x"}]']),
    ])
    jobs = extract_jobs_from_agent_result(result)
    assert len(jobs) == 1 and jobs[0]["company"] == "测试公司"


def test_legacy_fallback_ignores_clamped_content():
    result = Result(iterations=[Iter(
        tool_calls=[{"name": "search_jobs", "id": "c1"}],
        tool_results=['[{"company": "a", "title": "截断' + "x" * 7000],
    )])
    assert extract_jobs_from_agent_result(result) == []


def test_none_and_empty_results_safe():
    assert extract_jobs_from_agent_result(None) == []
    assert extract_jobs_from_agent_result(Result()) == []
