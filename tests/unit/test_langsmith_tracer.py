"""LangSmith 追踪模块测试（AGENT_LANGSMITH_SPEC Part B）。

覆盖：masking 截断/打码、settings 解析、key 缺失 fail-fast、
``get_cached_client(anonymizer=...)`` 预置后 LangChain 自动追踪复用同一 client、
run 列表/详情序列化与根 run 过滤、404/503 分支。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from careercrew_core.state.settings import LangSmithSettings, SettingsError, validate_settings
from careercrew_core.tracing.langsmith import (
    RunNotFoundError,
    configure_langsmith,
    get_run_detail,
    list_runs,
    make_anonymizer,
    serialize_run_summary,
    tracing_enabled,
)


def _disabled_settings():
    return SimpleNamespace(
        langsmith=SimpleNamespace(
            enabled=False, project="", api_key="", masking=True, max_chars=2000
        )
    )


def _reset() -> None:
    configure_langsmith(_disabled_settings())


_TRACING_ENV_KEYS = (
    "LANGCHAIN_TRACING_V2",
    "LANGCHAIN_PROJECT",
    "LANGSMITH_TRACING",
    "LANGSMITH_API_KEY",
)


@pytest.fixture(autouse=True)
def _reset_tracing_after_each():
    """每个用例后复位追踪状态与追踪环境变量。

    configure_langsmith 直接写 os.environ（monkeypatch 不追踪普通赋值），
    若不清除会把 LANGCHAIN_TRACING_V2=true 泄漏到其他测试文件，
    导致 LangChain 自动追踪用假 key 上传（403）。这里用 pop 直接清，
    避免 monkeypatch.delenv 在 undo 时把原值恢复回来。
    """
    yield
    for key in _TRACING_ENV_KEYS:
        os.environ.pop(key, None)
    _reset()


# ── masking ──


def test_anonymizer_masks_and_truncates() -> None:
    anon = make_anonymizer(max_chars=20)
    payload = {
        "phone": "13800138000",
        "email": "zhangsan@example.com",
        "salary": "期望 30-40K，最低 25万",
        "nested": [{"note": "联系 13912345678 或 lisi@foo.com"}, "A" * 100],
        "plain": 42,
    }
    out = anon(payload)
    assert "手机号已隐藏" in out["phone"]
    assert "邮箱已隐藏" in out["email"]
    assert "30-40K" not in out["salary"] and "25万" not in out["salary"]
    assert "13912345678" not in out["nested"][0]["note"]
    assert out["nested"][1].endswith("…[已截断]")
    assert len(out["nested"][1]) <= 20 + len("…[已截断]")
    assert out["plain"] == 42


def test_anonymizer_off_when_masking_disabled(valid_settings) -> None:
    settings = valid_settings.model_copy(
        update={"langsmith": valid_settings.langsmith.model_copy(update={"masking": False})}
    )
    captured: dict = {}

    def fake_get_cached_client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("langsmith.run_trees.get_cached_client", fake_get_cached_client)
    try:
        configure_langsmith(settings)
        assert captured["anonymizer"] is None
    finally:
        _reset()
        monkeypatch.undo()


# ── settings / fail-fast ──


def test_langsmith_settings_parse(valid_config_data) -> None:
    cfg = LangSmithSettings.model_validate(valid_config_data["langsmith"])
    assert cfg.enabled is True
    assert cfg.project == "careercrew"
    assert cfg.masking is True
    assert cfg.max_chars == 2000


def test_langsmith_key_missing_fails_fast(valid_settings) -> None:
    settings = valid_settings.model_copy(
        update={"langsmith": LangSmithSettings(enabled=True, project="careercrew", api_key="")}
    )
    with pytest.raises(SettingsError) as exc:
        validate_settings(settings)
    assert "langsmith.api_key" in str(exc.value)


def test_langsmith_disabled_skips_key_check(valid_settings) -> None:
    settings = valid_settings.model_copy(
        update={"langsmith": LangSmithSettings(enabled=False, project="careercrew", api_key="")}
    )
    validate_settings(settings)  # 不抛


# ── configure_langsmith：预置带 anonymizer 的缓存 client，LangChainTracer 复用 ──


def test_configure_preloads_masked_client(valid_settings, monkeypatch) -> None:
    captured: dict = {}

    def fake_get_cached_client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("langsmith.run_trees.get_cached_client", fake_get_cached_client)
    try:
        configure_langsmith(valid_settings)
        assert captured["api_key"] == "lsv2-test-literal"
        assert captured["anonymizer"] is not None
        assert os.environ.get("LANGCHAIN_TRACING_V2") == "true"
        assert os.environ.get("LANGCHAIN_PROJECT") == "careercrew"
        assert tracing_enabled() is True
        # 预置的 anonymizer 实际生效
        masked = captured["anonymizer"]({"phone": "13800138000"})
        assert masked["phone"] == "[手机号已隐藏]"
    finally:
        _reset()


def test_langchain_tracer_reuses_cached_client(monkeypatch) -> None:
    """LangChainTracer(client=None) 会复用 get_cached_client 的进程级单例。"""
    fake_client = object()
    monkeypatch.setattr("langsmith.run_trees.get_cached_client", lambda **kwargs: fake_client)
    from langchain_core.tracers.langchain import LangChainTracer

    tracer = LangChainTracer()
    assert tracer.client is fake_client


def test_client_missing_key_raises_readable(monkeypatch) -> None:
    """未配置 LANGSMITH_API_KEY 且 .env 也无 key 时，读取接口抛可读错误（→503 文案）。"""
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    for key in _TRACING_ENV_KEYS:
        os.environ.pop(key, None)
    from careercrew_core.tracing.langsmith import _client

    with pytest.raises(RuntimeError, match="LANGSMITH_API_KEY"):
        _client()


# ── run 序列化 / 根 run 过滤 / 详情 ──


def _make_run(
    run_id: str,
    name: str,
    *,
    parent: str | None = None,
    user_id: str = "u1",
    thread_id: str = "t1",
    stage: str = "match",
    tokens: int | None = 150,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=run_id,
        name=name,
        run_type="chain",
        start_time=datetime(2026, 8, 11, 10, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 8, 11, 10, 0, 5, tzinfo=timezone.utc),
        status="success",
        error=None,
        metadata={"user_id": user_id, "thread_id": thread_id, "stage": stage},
        total_tokens=tokens,
        prompt_tokens=100 if tokens else None,
        completion_tokens=50 if tokens else None,
        extra={"metadata": {"model_name": "deepseek-ai/DeepSeek-V4-Flash"}},
        parent_run_id=parent,
        inputs={"q": "你好"},
        outputs={"a": "你好"},
        child_runs=[],
    )


def test_serialize_run_summary() -> None:
    run = _make_run("run-1", "careercrew.match")
    s = serialize_run_summary(run)
    assert s["run_id"] == "run-1"
    assert s["duration_ms"] == 5000
    assert s["total_tokens"] == 150
    assert s["estimated_cost"] is None  # 价格表未配置 -> null
    assert s["metadata"]["stage"] == "match"


def test_list_runs_filters_roots_by_metadata(monkeypatch) -> None:
    runs = [
        _make_run("r1", "careercrew.match", user_id="u1", thread_id="t1", stage="match"),
        _make_run("r2", "careercrew.resume", user_id="u2", thread_id="t2", stage="resume"),
        _make_run("r3", "agent.job_matcher", parent="r1", user_id="u1", thread_id="t1", stage="match"),
    ]
    calls: dict = {}

    class FakeClient:
        def list_runs(self, **kwargs):
            calls.update(kwargs)
            return iter(runs)

    monkeypatch.setattr("careercrew_core.tracing.langsmith._client", lambda: FakeClient())
    try:
        out = list_runs(limit=10, user_id="u1", stage="match")
        assert calls.get("is_root") is True  # 服务端只取根 run
        assert [r["run_id"] for r in out] == ["r1"]
        out_all = list_runs(limit=10)
        assert [r["run_id"] for r in out_all] == ["r1", "r2"]  # r3 子 run 被过滤
    finally:
        _reset()


def test_get_run_detail_flattens_steps(monkeypatch) -> None:
    child = SimpleNamespace(
        id="llm-1",
        name="ChatOpenAI",
        run_type="llm",
        start_time=datetime(2026, 8, 11, 10, 0, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 8, 11, 10, 0, 3, tzinfo=timezone.utc),
        status="success",
        error=None,
        total_tokens=150,
        prompt_tokens=100,
        completion_tokens=50,
        inputs={"messages": [["human", "A" * 1000]]},
        outputs={"generations": [["assistant", "hi"]]},
        child_runs=[],
    )
    run = _make_run("run-1", "careercrew.match")
    run.child_runs = [child]

    class FakeClient:
        def read_run(self, run_id, load_child_runs=False):
            assert load_child_runs is True
            return run

    monkeypatch.setattr("careercrew_core.tracing.langsmith._client", lambda: FakeClient())
    try:
        detail = get_run_detail("run-1")
        assert detail["run"]["run_id"] == "run-1"
        assert detail["steps"][0]["run_type"] == "llm"
        assert detail["steps"][0]["duration_ms"] == 2000
        assert len(detail["steps"][0]["inputs_preview"]) <= 500 + len("…[已截断]")
        assert "…[已截断]" in detail["steps"][0]["inputs_preview"]
    finally:
        _reset()


def test_get_run_detail_not_found_raises(monkeypatch) -> None:
    class NotFound(RuntimeError):
        status_code = 404

    class FakeClient:
        def read_run(self, run_id, load_child_runs=False):
            raise NotFound("not found")

    monkeypatch.setattr("careercrew_core.tracing.langsmith._client", lambda: FakeClient())
    try:
        with pytest.raises(RunNotFoundError):
            get_run_detail("nope")
    finally:
        _reset()
