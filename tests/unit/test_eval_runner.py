"""评估 runner 指标函数单元测试。"""
from __future__ import annotations

import json

import pytest

from scripts import eval_runner
from scripts.eval_runner import (
    EvalCaseError,
    EvalInfrastructureError,
    bad_case_pass_rate,
    build_experiment_metadata,
    check_consult_bounds,
    citation_coverage,
    collect_real,
    compare_baseline,
    hit_at_k,
    load_cases,
    main,
    mrr,
    normalize_bad_case,
    route_accuracy,
    tool_success,
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


def test_collect_real_uses_injected_adapter_without_live_network():
    seen: dict[str, object] = {}

    def fake_adapter(case: dict, metadata: dict) -> dict:
        seen["case"] = case
        seen["metadata"] = metadata
        return {"route": "salary_negotiator", "tokens": 12}

    metadata = build_experiment_metadata(dataset_version="test-v1", model_identifier="fake")
    observation = collect_real(
        {"case_id": "route-1", "kind": "route", "question": "private question", "expected": {}},
        adapter=fake_adapter,
        metadata=metadata,
    )

    assert observation["route"] == "salary_negotiator"
    assert observation["tokens"] == 12
    assert seen["case"]["case_id"] == "route-1"
    assert seen["metadata"]["run_id"] == metadata["run_id"]


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


def test_real_cli_rejects_conflicting_skip_and_required_modes(monkeypatch):
    monkeypatch.setattr(
        eval_runner,
        "load_cases",
        lambda path=eval_runner.CASES_PATH, **_kwargs: [{
            "case_id": "route-1", "kind": "route", "question": "q", "expected": {"route": "x"},
        }],
    )
    monkeypatch.setattr(eval_runner, "collect_real", lambda *_args, **_kwargs: pytest.fail("must not collect"))

    with pytest.raises(SystemExit):
        main(["--real", "--allow-skip", "--require-real"])


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


def test_real_cli_allows_explicit_configuration_skip_but_require_real_fails(monkeypatch, capsys, tmp_path):
    cases = [{"case_id": "route-1", "kind": "route", "question": "q", "expected": {"route": "x"}}]
    monkeypatch.setattr(eval_runner, "load_cases", lambda path=eval_runner.CASES_PATH: cases)

    def unavailable(*_args, **_kwargs):
        raise EvalInfrastructureError("configuration", "settings unavailable")

    monkeypatch.setattr(eval_runner, "collect_real", unavailable)
    report = tmp_path / "skip-report.json"

    assert main(["--real", "--allow-skip", "--report", str(report)]) == 0
    assert "skipped" in capsys.readouterr().out
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "skipped"
    assert main(["--real", "--require-real"]) != 0


def test_real_cli_never_converts_provider_failure_to_optional_skip(monkeypatch):
    cases = [{"case_id": "route-1", "kind": "route", "question": "q", "expected": {"route": "x"}}]
    monkeypatch.setattr(eval_runner, "load_cases", lambda path=eval_runner.CASES_PATH: cases)
    monkeypatch.setattr(
        eval_runner,
        "collect_real",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(EvalInfrastructureError("provider", "request failed")),
    )

    assert main(["--real", "--allow-skip"]) != 0


def test_real_collection_reports_safe_error_latency_and_token_fields():
    case = {"case_id": "route-1", "kind": "route", "question": "q", "expected": {"route": "x"}}

    def provider_failure(_case: dict, _metadata: dict) -> dict:
        raise EvalInfrastructureError("provider", "private provider response")

    _observations, case_reports, errors = eval_runner.collect_real_observations(
        [case], build_experiment_metadata(), adapter=provider_failure,
    )

    assert case_reports == [{
        "case_id": "route-1", "kind": "route", "latency_s": None,
        "tokens": None, "error_code": "provider",
    }]
    assert errors == [{"case_id": "route-1", "kind": "route", "error_code": "provider"}]


def test_faster_latency_is_not_a_baseline_regression():
    assert compare_baseline(
        {"route_accuracy": 1.0, "consult_avg_latency_s": 100.0, "consult_avg_tokens": 3000.0},
        {"route_accuracy": 1.0, "consult_avg_latency_s": 120.0, "consult_avg_tokens": 4000.0},
    ) == []
