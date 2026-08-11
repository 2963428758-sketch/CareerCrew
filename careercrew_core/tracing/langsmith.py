"""LangSmith 全链路追踪（AGENT_LANGSMITH_SPEC Part B）。

机制要点：
- ``configure_langsmith`` 必须**先于任何 LLM 调用**执行（``_ensure_heavy`` 中
  ``create_llm`` 之前）：设置 ``LANGCHAIN_TRACING_V2`` / ``LANGCHAIN_PROJECT``，
  并用 ``get_cached_client(api_key=..., anonymizer=...)`` 预置进程级缓存 client。
  LangChainTracer 的 ``get_client()`` 无参返回该缓存单例，因此 LangChain 自动捕获的
  LLM/工具 run 全部经过 anonymizer 脱敏。
- ``traced_call``：LangSmith 启用时才包 ``traceable``（根 run 纪律），未启用时直通，
  测试与本地无 key 场景零网络副作用。
- 读取侧 ``list_runs`` / ``get_run_detail`` 供 ``/api/runs`` 使用。
"""
from __future__ import annotations

import json
import os
import re
import threading
from typing import Any, Callable

_ENABLED = False
_ENABLED_LOCK = threading.Lock()

# 手机号 / 邮箱 / 薪资数字（脱敏正则）
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_SALARY_RE = re.compile(
    r"\d{1,3}(?:\.\d+)?\s*[Kk](?:\s*[-~]\s*\d{1,3}(?:\.\d+)?\s*[Kk])?"
    r"|\d{1,3}\s*[-~]\s*\d{1,3}\s*[Kk]"
    r"|\d{1,3}(?:\.\d+)?\s*万"
)
_TRUNC_SUFFIX = "…[已截断]"

# 内置价格表：模型名 -> (每 1k prompt token 元, 每 1k completion token 元)
# 未知模型返回 null（前端显示 "—"）。
MODEL_PRICING: dict[str, tuple[float, float] | None] = {
    "deepseek-ai/DeepSeek-V4-Flash": None,  # 未配置单价，后续按需补
}


def _mask_value(value: Any, max_chars: int) -> Any:
    if isinstance(value, str):
        v = _PHONE_RE.sub("[手机号已隐藏]", value)
        v = _EMAIL_RE.sub("[邮箱已隐藏]", v)
        v = _SALARY_RE.sub("[薪资已隐藏]", v)
        if len(v) > max_chars:
            v = v[:max_chars] + _TRUNC_SUFFIX
        return v
    if isinstance(value, list):
        return [_mask_value(x, max_chars) for x in value]
    if isinstance(value, dict):
        return {k: _mask_value(x, max_chars) for k, x in value.items()}
    return value


def make_anonymizer(max_chars: int = 2000) -> Callable[[dict], dict]:
    """递归处理所有字符串叶子：截断 + 打码手机号/邮箱/薪资。"""

    def anonymizer(payload: dict) -> dict:
        if not isinstance(payload, dict):
            return payload
        return _mask_value(payload, max_chars)

    return anonymizer


def tracing_enabled() -> bool:
    return _ENABLED


def configure_langsmith(settings) -> None:
    """配置 LangSmith：校验 key、设环境变量、预置带 anonymizer 的缓存 client。"""
    global _ENABLED
    cfg = settings.langsmith
    if not cfg.enabled:
        _ENABLED = False
        return
    api_key = (cfg.api_key or "").strip()
    if not api_key or "${" in api_key:
        # 语义校验在 validate_settings 已 fail-fast；此处双保险直接禁用
        _ENABLED = False
        return
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ["LANGCHAIN_PROJECT"] = cfg.project
    os.environ["LANGSMITH_API_KEY"] = api_key

    from langsmith.run_trees import get_cached_client

    get_cached_client(
        api_key=api_key,
        anonymizer=make_anonymizer(cfg.max_chars) if cfg.masking else None,
    )
    with _ENABLED_LOCK:
        _ENABLED = True


def traced_call(fn: Callable, *, name: str | None = None, run_type: str = "chain",
                run_metadata: dict | None = None, **kwargs: Any) -> Any:
    """LangSmith 启用时以 ``traceable`` 包一层（根 run），否则直通。"""
    if not tracing_enabled():
        return fn(**kwargs)
    from langsmith import traceable

    wrapped = traceable(fn, name=name, run_type=run_type, metadata=run_metadata or {})
    return wrapped(**kwargs)


def attach_run_metadata(**fields: Any) -> None:
    """给当前 traceable run 合并 metadata（user_id/thread_id/stage 等）。"""
    if not tracing_enabled():
        return
    try:
        from langsmith import get_current_run_tree

        tree = get_current_run_tree()
        if tree is None:
            return
        tree.add_metadata(dict(fields))
        tree.post()
    except Exception:  # noqa: BLE001 - 埋点失败不影响主链路
        pass


def _serialize_dt(value) -> str | None:
    return value.isoformat() if value is not None else None


def _duration_ms(start, end) -> int | None:
    if start is None or end is None:
        return None
    try:
        return int((end - start).total_seconds() * 1000)
    except Exception:  # noqa: BLE001
        return None


def _estimated_cost(run) -> float | None:
    tokens = getattr(run, "total_tokens", None)
    if not tokens:
        return None
    extra = getattr(run, "extra", None) or {}
    meta = extra.get("metadata") or {}
    model = meta.get("model_name") or meta.get("model")
    pricing = MODEL_PRICING.get(model) if model else None
    if not pricing:
        return None
    prompt = getattr(run, "prompt_tokens", 0) or 0
    completion = getattr(run, "completion_tokens", 0) or 0
    return round(prompt / 1000 * pricing[0] + completion / 1000 * pricing[1], 4)


def serialize_run_summary(run) -> dict:
    """Run schema -> RunSummary（前端契约）。"""
    return {
        "run_id": str(run.id),
        "name": getattr(run, "name", ""),
        "run_type": getattr(run, "run_type", ""),
        "start_time": _serialize_dt(getattr(run, "start_time", None)),
        "end_time": _serialize_dt(getattr(run, "end_time", None)),
        "duration_ms": _duration_ms(getattr(run, "start_time", None), getattr(run, "end_time", None)),
        "status": getattr(run, "status", ""),
        "error": getattr(run, "error", None),
        "metadata": dict(getattr(run, "metadata", None) or {}),
        "prompt_tokens": getattr(run, "prompt_tokens", None),
        "completion_tokens": getattr(run, "completion_tokens", None),
        "total_tokens": getattr(run, "total_tokens", None),
        "estimated_cost": _estimated_cost(run),
    }


def _preview(value: Any, max_chars: int = 500) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        text = str(value)
    if len(text) > max_chars:
        return text[:max_chars] + _TRUNC_SUFFIX
    return text


class RunNotFoundError(LookupError):
    """LangSmith 中不存在指定 run。"""


def _client():
    from langsmith.run_trees import get_cached_client

    return get_cached_client()


def list_runs(
    limit: int = 50,
    user_id: str | None = None,
    thread_id: str | None = None,
    stage: str | None = None,
    project: str | None = None,
) -> list[dict]:
    """列根 run（一次用户请求=一条根 run），按 metadata 过滤。"""
    project = project or os.environ.get("LANGCHAIN_PROJECT") or "careercrew"
    fetch = min(max(limit * 3, limit), 200)
    runs = list(_client().list_runs(project_name=project, is_root=True, limit=fetch))
    out: list[dict] = []
    for run in runs:
        if getattr(run, "parent_run_id", None) is not None:
            continue  # 服务端 is_root=True 已过滤，Python 侧兜底
        meta = dict(getattr(run, "metadata", None) or {})
        if user_id and meta.get("user_id") != user_id:
            continue
        if thread_id and meta.get("thread_id") != thread_id:
            continue
        if stage and meta.get("stage") != stage:
            continue
        out.append(serialize_run_summary(run))
        if len(out) >= limit:
            break
    return out


def get_run_detail(run_id: str) -> dict:
    """run + 展平子 run 时间线（steps）。"""
    try:
        run = _client().read_run(run_id, load_child_runs=True)
    except Exception as e:  # noqa: BLE001
        if getattr(e, "status_code", None) == 404 or "not found" in str(e).lower():
            raise RunNotFoundError(run_id) from e
        raise
    steps: list[dict] = []
    queue: list = list(getattr(run, "child_runs", None) or [])
    while queue:
        child = queue.pop(0)
        steps.append(
            {
                "run_id": str(child.id),
                "name": getattr(child, "name", ""),
                "run_type": getattr(child, "run_type", ""),
                "start_time": _serialize_dt(getattr(child, "start_time", None)),
                "end_time": _serialize_dt(getattr(child, "end_time", None)),
                "duration_ms": _duration_ms(getattr(child, "start_time", None), getattr(child, "end_time", None)),
                "status": getattr(child, "status", ""),
                "error": getattr(child, "error", None),
                "prompt_tokens": getattr(child, "prompt_tokens", None),
                "completion_tokens": getattr(child, "completion_tokens", None),
                "total_tokens": getattr(child, "total_tokens", None),
                "inputs_preview": _preview(getattr(child, "inputs", None)),
                "outputs_preview": _preview(getattr(child, "outputs", None)),
            }
        )
        queue.extend(list(getattr(child, "child_runs", None) or []))
    return {"run": serialize_run_summary(run), "steps": steps}
