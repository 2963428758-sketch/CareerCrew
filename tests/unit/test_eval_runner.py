"""评估 runner 指标函数单元测试。"""
from __future__ import annotations

import json

import pytest

from scripts import eval_runner
from scripts.eval_runner import (
    EvalCaseError,
    EvalInfrastructureError,
    RuntimeEvalSession,
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
    validate_prompt_version,
    validate_runtime_eval_environment,
    verify_runtime_eval_tenant_attestation,
)


def _runtime_env() -> dict[str, str]:
    return {
        "CAREERCREW_EVAL_RUNTIME": "1",
        "CAREERCREW_EVAL_USER_ID": "eval_demo",
        "CAREERCREW_EVAL_RUN_ID": "demo",
        "CAREERCREW_EVAL_TENANT_ATTESTATION": "eval_demo:demo:provisioned",
    }


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


@pytest.mark.parametrize("value", ["bad version", "bad\nversion", "x" * 65, "../escape"])
def test_prompt_version_is_a_safe_identifier(value: str) -> None:
    with pytest.raises(EvalCaseError, match="prompt_version"):
        validate_prompt_version(value)


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

    assert main(["--real", "--model-probe", "--allow-skip", "--report", str(report)]) == 0
    assert "skipped" in capsys.readouterr().out
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "skipped"
    with pytest.raises(SystemExit):
        main(["--real", "--model-probe", "--require-real"])


def test_real_cli_never_converts_provider_failure_to_optional_skip(monkeypatch):
    cases = [{"case_id": "route-1", "kind": "route", "question": "q", "expected": {"route": "x"}}]
    monkeypatch.setattr(eval_runner, "load_cases", lambda path=eval_runner.CASES_PATH: cases)
    monkeypatch.setattr(
        eval_runner,
        "collect_real",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(EvalInfrastructureError("provider", "request failed")),
    )

    assert main(["--real", "--model-probe", "--allow-skip"]) != 0


def test_protected_real_eval_requires_runtime_mode():
    with pytest.raises(SystemExit):
        main(["--real", "--require-real", "--model-probe"])


def test_runtime_eval_requires_protected_marker_and_dedicated_user():
    with pytest.raises(EvalInfrastructureError, match="CAREERCREW_EVAL_RUNTIME"):
        validate_runtime_eval_environment({"CAREERCREW_EVAL_USER_ID": "eval_demo"})

    with pytest.raises(EvalInfrastructureError, match="eval_"):
        validate_runtime_eval_environment({
            "CAREERCREW_EVAL_RUNTIME": "1",
            "CAREERCREW_EVAL_USER_ID": "production-user",
            "CAREERCREW_EVAL_RUN_ID": "production",
            "CAREERCREW_EVAL_TENANT_ATTESTATION": "production-user:production:provisioned",
        })

    with pytest.raises(EvalInfrastructureError, match="run"):
        validate_runtime_eval_environment({
            "CAREERCREW_EVAL_RUNTIME": "1",
            "CAREERCREW_EVAL_USER_ID": "eval_demo",
        })

    valid = _runtime_env()
    assert validate_runtime_eval_environment(valid) == "eval_demo"

    invalid_attestation = _runtime_env()
    invalid_attestation["CAREERCREW_EVAL_TENANT_ATTESTATION"] = "eval_demo:demo:other"
    with pytest.raises(EvalInfrastructureError, match="attestation"):
        validate_runtime_eval_environment(invalid_attestation)


def test_protected_runtime_eval_requires_external_tenant_attestation():
    with pytest.raises(EvalInfrastructureError, match="external tenant attestation"):
        validate_runtime_eval_environment(_runtime_env(), require_remote_attestation=True)


def test_external_tenant_attestation_rejects_invalid_port():
    env = _runtime_env()
    env.update({
        "CAREERCREW_EVAL_TENANT_ATTESTATION_URL": "https://provisioner.example:99999/v1/eval-tenants",
        "CAREERCREW_EVAL_TENANT_ATTESTATION_TOKEN": "provisioner-secret",
        "CAREERCREW_EVAL_TENANT_ATTESTATION_NONCE": "nonce-demo-123",
    })

    with pytest.raises(EvalInfrastructureError, match="URL"):
        verify_runtime_eval_tenant_attestation(env)


def test_external_tenant_attestation_must_match_nonce_and_scope(monkeypatch):
    import scripts.eval_runner as runner

    env = _runtime_env()
    env.update({
        "CAREERCREW_EVAL_TENANT_ATTESTATION_URL": "https://provisioner.example/v1/eval-tenants",
        "CAREERCREW_EVAL_TENANT_ATTESTATION_TOKEN": "provisioner-secret",
        "CAREERCREW_EVAL_TENANT_ATTESTATION_NONCE": "nonce-demo-123",
    })
    seen: list[dict[str, object]] = []
    env.update(DATABASE_URL="postgresql://user:secret@eval-db.example/eval", QDRANT_URL="https://eval-qdrant.example")
    binding = {"database": {"host": "eval-db.example", "port": 5432, "database": "eval"}, "qdrant": "https://eval-qdrant.example:443"}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "status": "provisioned",
                "user_id": "eval_demo",
                "run_id": "demo",
                "nonce": "nonce-demo-123",
                "tenant_id": "eval_demo",
                "expires_at": "2099-01-01T00:00:00Z",
                "attestation_id": "tenant-attestation-1",
                "deployment": binding,
            }

    def fake_post(url: str, **kwargs):
        seen.append({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr(runner.requests, "post", fake_post)
    receipt = verify_runtime_eval_tenant_attestation(env)

    assert receipt["attestation_id"] == "tenant-attestation-1"
    assert seen[0]["headers"] == {"Authorization": "Bearer provisioner-secret"}
    assert seen[0]["json"] == {
        "contract": "careercrew-eval-tenant-v1",
        "user_id": "eval_demo",
        "run_id": "demo",
        "nonce": "nonce-demo-123",
        "deployment": binding,
    }

    switched = dict(env, DATABASE_URL="postgresql://user:secret@production.example/eval")
    with pytest.raises(EvalInfrastructureError, match="deployment"):
        verify_runtime_eval_tenant_attestation(switched)

    bad = dict(env)
    bad["CAREERCREW_EVAL_TENANT_ATTESTATION_NONCE"] = "other-nonce"
    with pytest.raises(EvalInfrastructureError, match="nonce"):
        verify_runtime_eval_tenant_attestation(bad)


def test_runtime_eval_cleanup_is_thread_scoped_and_never_deletes_whole_user():
    deleted_conversations: list[tuple[str, str]] = []
    deleted_threads: list[tuple[str, str]] = []

    class ConversationStore:
        def delete_conversation(self, thread_id, user_id):
            deleted_conversations.append((thread_id, user_id))
            return True

    class ThreadStore:
        def delete_all_for_thread(self, user_id, thread_id):
            deleted_threads.append((user_id, thread_id))
            return 1

    class Runtime:
        conversation_store = ConversationStore()
        thread_store = ThreadStore()
        _cycles = {}

        def _ensure_heavy(self):
            return None

        def db_delete_all_for_user(self, _user_id):
            pytest.fail("runtime evaluation must not purge the whole tenant")

    session = RuntimeEvalSession(
        build_experiment_metadata(),
        environ=_runtime_env(),
        runtime_factory=Runtime,
    )
    session._cleanup_thread("thread-1")

    assert deleted_conversations == [("thread-1", "eval_demo")]
    assert deleted_threads == [("eval_demo", "thread-1")]


def test_runtime_eval_cleanup_removes_eval_vectors_and_memory_only():
    from careercrew_core.memory.db import FakeMemoryDb
    from careercrew_core.memory.policy import MemoryPolicyStore
    from careercrew_core.memory.service import MemoryService

    db = FakeMemoryDb()
    policy = MemoryPolicyStore(db)
    policy.set_global(enabled=True, generate=True, use=True)
    policy.set_user("eval_demo", enabled=True, generate=True, use=True)
    policy.set_user("other_user", enabled=True, generate=True, use=True)
    service = MemoryService(db, policy_store=policy, feature_enabled=True)
    service.save_explicit("eval_demo", name="profile.direction", value="AI")
    service.save_explicit("other_user", name="profile.direction", value="Java")

    class VectorStore:
        def __init__(self):
            self.filters = []
            self.remaining = False

        def delete_by_metadata(self, filters):
            self.filters.append(filters)
            self.remaining = False
            return 1

        def metadata_exists(self, _filters):
            return self.remaining

    vector_store = VectorStore()

    class ConversationStore:
        def delete_conversation(self, _thread_id, _user_id):
            return True

    class ThreadStore:
        def delete_all_for_thread(self, _user_id, _thread_id):
            return 1

    class Runtime:
        conversation_store = ConversationStore()
        thread_store = ThreadStore()
        memory_service = service
        _episodic_vector_store = vector_store
        _cycles = {}

        def _ensure_heavy(self):
            return None

        def db_delete_all_for_user(self, _user_id):
            pytest.fail("runtime evaluation must not purge the whole tenant")

    metadata = build_experiment_metadata()
    session = RuntimeEvalSession(
        metadata,
        environ=_runtime_env(),
        runtime_factory=Runtime,
    )
    session.close()

    assert vector_store.filters == [{"user_id": "eval_demo"}]
    assert service.records.list_active("eval_demo") == []
    assert len(service.records.list_active("other_user")) == 1
    assert metadata["runtime_cleanup"]["records_deleted"] == 1


def test_runtime_eval_cleanup_fails_closed_on_residual_eval_vectors():
    from careercrew_core.memory.db import FakeMemoryDb
    from careercrew_core.memory.policy import MemoryPolicyStore
    from careercrew_core.memory.service import MemoryService

    db = FakeMemoryDb()
    policy = MemoryPolicyStore(db)
    policy.set_global(enabled=True, generate=True, use=True)
    policy.set_user("eval_demo", enabled=True, generate=True, use=True)
    service = MemoryService(db, policy_store=policy, feature_enabled=True)
    service.save_explicit("eval_demo", name="profile.direction", value="AI")

    class VectorStore:
        def delete_by_metadata(self, _filters):
            return 1

        def metadata_exists(self, _filters):
            return True

    class Runtime:
        memory_service = service
        _episodic_vector_store = VectorStore()
        _cycles = {}

        def _ensure_heavy(self):
            return None

        def db_delete_all_for_user(self, _user_id):
            pytest.fail("runtime evaluation must not purge the whole tenant")

    session = RuntimeEvalSession(
        build_experiment_metadata(),
        environ=_runtime_env(),
        runtime_factory=Runtime,
    )

    with pytest.raises(EvalInfrastructureError, match="cleanup"):
        session.close()
    assert service.records.list_active("eval_demo") == []


def test_runtime_eval_cleanup_fails_closed_on_database_residuals():
    class Records:
        def cleanup_eval_tenant(self, _user_id):
            return {"records_deleted": 0, "outbox_remaining": 1, "records_remaining": 0}

    class Runtime:
        memory_service = type("MemoryService", (), {"records": Records()})()
        _cycles = {}

        def _ensure_heavy(self):
            return None

    session = RuntimeEvalSession(
        build_experiment_metadata(),
        environ=_runtime_env(),
        runtime_factory=Runtime,
    )

    with pytest.raises(EvalInfrastructureError, match="cleanup"):
        session.close()


def test_runtime_eval_uses_product_stream_observability_for_retrieval_and_tools():
    from types import SimpleNamespace

    class ConversationStore:
        def delete_conversation(self, _thread_id, _user_id):
            return True

    class ThreadStore:
        def delete_all_for_thread(self, _user_id, _thread_id):
            return 1

    class Runtime:
        conversation_store = ConversationStore()
        thread_store = ThreadStore()
        _cycles = {}

        def _ensure_heavy(self):
            return None

        def run_knowledge_ask_stream(self, *_args, **_kwargs):
            return SimpleNamespace(
                content="引用 d1 的回答",
                sources=[{"doc": "d1", "score": 0.9}],
                turn=object(),
                total_tokens=31,
            )

        def run_match_stream(self, *_args, **_kwargs):
            return SimpleNamespace(
                content="已搜索岗位",
                tool_calls=[{"tool_name": "search_jobs"}],
                turn=object(),
                total_tokens=17,
            )

    session = RuntimeEvalSession(
        build_experiment_metadata(),
        environ=_runtime_env(),
        runtime_factory=Runtime,
    )
    retrieval = session.run_case({
        "case_id": "r", "kind": "retrieval", "question": "q", "expected": {},
    }, {})
    tool = session.run_case({
        "case_id": "t", "kind": "tool", "question": "q", "expected": {},
    }, {})

    assert retrieval["retrieved"] == ["d1"]
    assert retrieval["tokens"] == 31
    assert tool["tools"] == ["search_jobs"]
    assert tool["tokens"] == 17


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


def test_cleanup_detects_vector_recreated_during_database_sweep():
    from types import SimpleNamespace

    points = set()

    class Store:
        def delete_by_metadata(self, _filters):
            points.clear()

        def metadata_exists(self, _filters):
            return bool(points)

    class Records:
        def cleanup_eval_tenant(self, user_id):
            # A previously claimed worker finishes after the first vector check.
            points.add(user_id)
            return {"outbox_remaining": 0, "records_remaining": 0}

    session = RuntimeEvalSession(
        {}, environ=_runtime_env(), runtime_factory=lambda: SimpleNamespace(
            _ensure_heavy=lambda: None,
            memory_service=SimpleNamespace(_vector_store=Store(), records=Records()),
        ),
    )
    with pytest.raises(EvalInfrastructureError, match="cleanup"):
        session.close()
    assert not session._memory_cleaned


def test_live_runtime_refuses_unproven_worker_lifecycle(monkeypatch):
    import sys
    from types import SimpleNamespace

    constructed = []
    monkeypatch.setitem(sys.modules, "careercrew_api.runtime", SimpleNamespace(
        get_runtime=lambda: constructed.append(True) or SimpleNamespace(_ensure_heavy=lambda: None),
    ))
    with pytest.raises(EvalInfrastructureError, match="worker"):
        RuntimeEvalSession({}, environ=_runtime_env())
    assert constructed == []


@pytest.mark.parametrize("database,qdrant", [
    ("postgresql://u@different/app", "https://q.example"),
    ("postgresql://u@expected/app", "https://different.example"),
])
def test_resolved_endpoint_mismatch_fails_before_runtime_construction(monkeypatch, database, qdrant):
    import sys
    from types import SimpleNamespace

    env = dict(_runtime_env(), DATABASE_URL="postgresql://u@expected/app", QDRANT_URL="https://q.example")
    settings = SimpleNamespace(
        memory=SimpleNamespace(postgres=SimpleNamespace(dsn=database)),
        vector_store=SimpleNamespace(url=qdrant),
    )
    import careercrew_core.state.settings as settings_module
    monkeypatch.setattr(settings_module, "load_settings", lambda: settings)
    constructed = []
    monkeypatch.setitem(sys.modules, "careercrew_api.runtime", SimpleNamespace(
        get_runtime=lambda: constructed.append(True) or SimpleNamespace(_ensure_heavy=lambda: None),
    ))
    with pytest.raises(EvalInfrastructureError, match="deployment"):
        RuntimeEvalSession({}, environ=env)
    assert constructed == []


def test_protected_adapter_cannot_bypass_missing_worker_isolation(monkeypatch):
    monkeypatch.setattr(eval_runner, "verify_runtime_eval_tenant_attestation", lambda _env: {})
    with pytest.raises(EvalInfrastructureError, match="worker") as error:
        RuntimeEvalSession(
            {}, environ=_runtime_env(), require_remote_attestation=True,
            runtime_factory=lambda: pytest.fail("must reject before construction"),
        )
    assert error.value.category == "isolation"


def test_missing_worker_isolation_cannot_be_optional_skip(monkeypatch, tmp_path):
    for key, value in _runtime_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("QDRANT_URL", raising=False)
    report = tmp_path / "isolation.json"
    assert main(["--real", "--runtime", "--allow-skip", "--report", str(report)]) != 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert {error["error_code"] for error in payload["errors"]} == {"isolation"}
