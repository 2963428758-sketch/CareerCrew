"""评估 runner 指标函数单元测试。"""
from __future__ import annotations

import json

import pytest

from scripts.eval_runner import (
    EvalCaseError,
    bad_case_pass_rate,
    build_experiment_metadata,
    check_consult_bounds,
    citation_coverage,
    compare_baseline,
    hit_at_k,
    load_cases,
    mrr,
    normalize_bad_case,
    route_accuracy,
    tool_success,
    validate_prompt_version,
)


def test_hit_at_k():
    assert hit_at_k([["d1", "d2"], ["d3"]], [["d2"], ["d3"]]) == 1.0
    assert hit_at_k([["d1", "d2"]], [["d9"]]) == 0.0


def test_mrr():
    assert mrr([["d1", "d2"], ["d9"]], [["d2"], ["d9"]]) == 0.75
    assert mrr([["d1"]], [["d9"]]) == 0.0


def test_citation_coverage():
    assert citation_coverage("答案A和B。", ["答案A", "B"]) == 1.0
    assert citation_coverage("只有答案A。", ["答案A", "缺失"]) == 0.5
    assert citation_coverage("空", []) == 1.0


def test_route_accuracy():
    assert route_accuracy(["a", "b", "c"], ["a", "x", "c"]) == 2 / 3
    assert route_accuracy([], []) == 1.0


def test_tool_success():
    assert tool_success([["search_jobs", "rag_query"]], [["search_jobs"]]) == 1.0
    assert tool_success([["rag_query"]], [["search_jobs"]]) == 0.0


def test_load_cases_normalizes_legacy_id_and_rejects_duplicate_or_invalid_schema(tmp_path):
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        json.dumps({"id": "legacy", "kind": "route", "question": "q", "expected": {"route": "x"}})
        + "\n",
        encoding="utf-8",
    )

    assert load_cases(cases_path) == [
        {"case_id": "legacy", "kind": "route", "question": "q", "expected": {"route": "x"}}
    ]

    cases_path.write_text(
        "\n".join([
            json.dumps({"case_id": "same", "kind": "route", "question": "q", "expected": {}}),
            json.dumps({"id": "same", "kind": "route", "question": "q2", "expected": {}}),
        ]),
        encoding="utf-8",
    )
    with pytest.raises(EvalCaseError, match="重复"):
        load_cases(cases_path)

    cases_path.write_text('{"case_id":"bad","kind":"unknown","question":"q"}\n', encoding="utf-8")
    with pytest.raises(EvalCaseError, match="不支持"):
        load_cases(cases_path)

    cases_path.write_text('{not json}\n', encoding="utf-8")
    with pytest.raises(EvalCaseError, match="JSON"):
        load_cases(cases_path)


def test_experiment_metadata_is_traceable_but_never_contains_business_text_or_secrets():
    secret_question = "客户简历 SECRET_TOKEN=never-report"
    metadata = build_experiment_metadata(
        dataset_version="2026-09-10.v1",
        model_provider="openai",
        model_identifier="qwen-plus",
        prompt_template="classify a question",
        temperature=0,
    )

    assert {"run_id", "code_sha", "dataset_version", "model_provider", "model_identifier",
            "prompt_version", "prompt_hash", "temperature", "collected_at"} <= set(metadata)
    assert secret_question not in json.dumps(metadata, ensure_ascii=False)
    assert "SECRET_TOKEN" not in json.dumps(metadata, ensure_ascii=False)


def test_experiment_metadata_supports_explicit_prompt_versions():
    metadata = build_experiment_metadata(
        prompt_version="careercrew-real-eval-v2",
        prompt_template="version two prompt",
    )

    assert metadata["prompt_version"] == "careercrew-real-eval-v2"
    assert metadata["prompt_hash"] == "0c1bb2a79c16de60"


@pytest.mark.parametrize("value", ["bad version", "bad\nversion", "x" * 65, "../escape"])
def test_prompt_version_is_a_safe_identifier(value: str) -> None:
    with pytest.raises(EvalCaseError, match="prompt_version"):
        validate_prompt_version(value)


def test_consult_bounds_and_bad_case_normalization_are_strict():
    consult = {
        "case_id": "consult-1",
        "kind": "consult",
        "question": "q",
        "expected": {"expected_agents": [], "max_latency_s": 1, "max_tokens": 10},
    }
    assert check_consult_bounds([consult], {"consult-1": {"latency_s": 2, "tokens": 11}}) == [
        "consult-1: latency_s 2.000 > max_latency_s 1.000",
        "consult-1: tokens 11 > max_tokens 10",
    ]

    normalized = normalize_bad_case({
        "id": "bad-1", "kind": "citation", "question": "q", "expected": "must say fallback",
    })
    assert normalized["case_id"] == "bad-1"
    assert normalized["rubric"] == {"must_include": ["must say fallback"]}
    assert bad_case_pass_rate([normalized], {"bad-1": {"answer": "no fallback"}}) == 0.0

    with pytest.raises(EvalCaseError, match="rubric"):
        normalize_bad_case({"case_id": "empty", "kind": "citation", "question": "q", "rubric": {}})


def test_faster_latency_is_not_a_baseline_regression():
    assert compare_baseline(
        {"route_accuracy": 1.0, "consult_avg_latency_s": 100.0, "consult_avg_tokens": 3000.0},
        {"route_accuracy": 1.0, "consult_avg_latency_s": 120.0, "consult_avg_tokens": 4000.0},
    ) == []


