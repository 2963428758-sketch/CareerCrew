"""Versioned offline and real-model evaluation with strict release semantics.

Offline observations are checked-in fixtures. Real observations always cross the
configured LLM boundary; unavailable infrastructure is never reported as a pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EVAL_DIR = Path(__file__).resolve().parents[1] / "data" / "eval"
CASES_PATH = EVAL_DIR / "cases.jsonl"
BASELINE_PATH = EVAL_DIR / "baseline.json"
REGRESSION_TOLERANCE = 0.01
DATASET_VERSION = "2026-09-10.v1"
DEFAULT_PROMPT_VERSION = "careercrew-real-eval-v1"
SUPPORTED_KINDS = {"route", "retrieval", "citation", "tool", "memory", "consult"}
RealEvalAdapter = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


class EvalCaseError(ValueError):
    """A dataset or model observation is invalid for evaluation."""


class EvalInfrastructureError(RuntimeError):
    """Safe classification for a real evaluation dependency failure."""

    def __init__(self, category: str, message: str) -> None:
        self.category = category
        super().__init__(message)


# ── Metrics (kept pure and backwards-compatible) ───────────────────────────


def hit_at_k(predicted: list[list[str]], expected: list[list[str]], k: int = 5) -> float:
    if not expected:
        return 1.0
    hits = [
        1.0 if any(doc_id in prediction[:k] for doc_id in wanted) else 0.0
        for prediction, wanted in zip(predicted, expected, strict=False)
    ]
    return sum(hits) / len(hits)


def mrr(predicted: list[list[str]], expected: list[list[str]]) -> float:
    if not expected:
        return 1.0
    scores = []
    for prediction, wanted in zip(predicted, expected, strict=False):
        best = 0.0
        for doc_id in wanted:
            try:
                best = max(best, 1.0 / (prediction.index(doc_id) + 1))
            except ValueError:
                continue
        scores.append(best)
    return sum(scores) / len(scores)


def citation_coverage(answer: str, must_include: list[str]) -> float:
    if not must_include:
        return 1.0
    return sum(1.0 for point in must_include if point in answer) / len(must_include)


def route_accuracy(predicted: list[str], expected: list[str]) -> float:
    if not expected:
        return 1.0
    return sum(1.0 for actual, wanted in zip(predicted, expected, strict=False) if actual == wanted) / len(expected)


def tool_success(tool_lists: list[list[str]], expected: list[list[str]]) -> float:
    if not expected:
        return 1.0
    results = [
        1.0 if all(tool in actual for tool in wanted) else 0.0
        for actual, wanted in zip(tool_lists, expected, strict=False)
    ]
    return sum(results) / len(results)


def retention(answer: str, points: list[str]) -> float:
    if not points:
        return 1.0
    return sum(1.0 for point in points if point in answer) / len(points)


# ── Dataset validation and normalization ────────────────────────────────────


def _case_id(case: dict[str, Any]) -> str:
    return str(case.get("case_id") or case.get("id") or "")


def _normalize_case(raw: dict[str, Any], *, line_number: int, bad_case: bool) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise EvalCaseError(f"第 {line_number} 行必须是 JSON object")
    case_id = raw.get("case_id", raw.get("id"))
    if not isinstance(case_id, str) or not case_id.strip():
        raise EvalCaseError(f"第 {line_number} 行缺少 case_id（兼容 id）")
    if "case_id" in raw and "id" in raw and raw["case_id"] != raw["id"]:
        raise EvalCaseError(f"第 {line_number} 行的 case_id 与 id 不一致")
    kind = raw.get("kind")
    if kind not in SUPPORTED_KINDS:
        raise EvalCaseError(f"第 {line_number} 行 kind 不支持: {kind!r}")
    question = raw.get("question")
    if not isinstance(question, str) or not question.strip():
        raise EvalCaseError(f"第 {line_number} 行缺少 question")
    if "expected" not in raw and not bad_case:
        raise EvalCaseError(f"第 {line_number} 行缺少 expected")
    if not bad_case and not isinstance(raw.get("expected"), dict):
        raise EvalCaseError(f"第 {line_number} 行 expected 必须是 object")
    normalized = {key: value for key, value in raw.items() if key != "id"}
    normalized["case_id"] = case_id.strip()
    return normalize_bad_case(normalized) if bad_case else normalized


def load_cases(path: Path = CASES_PATH, *, bad_cases: bool = False) -> list[dict[str, Any]]:
    """Load JSONL deterministically, validating each record before collection."""
    if not path.exists():
        return []
    loaded: list[dict[str, Any]] = []
    ids: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvalCaseError(f"第 {line_number} 行 JSON 格式错误") from exc
        case = _normalize_case(raw, line_number=line_number, bad_case=bad_cases)
        if case["case_id"] in ids:
            raise EvalCaseError(f"第 {line_number} 行 case_id 重复: {case['case_id']}")
        ids.add(case["case_id"])
        loaded.append(case)
    return loaded


def normalize_bad_case(case: dict[str, Any]) -> dict[str, Any]:
    """Turn promoted bad-case ``expected`` forms into a non-empty text rubric."""
    normalized = dict(case)
    case_id = _case_id(normalized)
    if not case_id:
        raise EvalCaseError("bad-case 缺少 case_id")
    normalized.pop("id", None)
    normalized["case_id"] = case_id
    rubric = normalized.get("rubric")
    if rubric is None:
        expected = normalized.get("expected")
        if isinstance(expected, str) and expected.strip():
            rubric = {"must_include": [expected.strip()]}
        elif isinstance(expected, list) and all(isinstance(item, str) and item.strip() for item in expected):
            rubric = {"must_include": expected}
        elif isinstance(expected, dict) and any(key in expected for key in ("must_include", "must_not_contain")):
            rubric = expected
        else:
            raise EvalCaseError(f"bad-case {case_id} 缺少可评分的 rubric/expected")
    if not isinstance(rubric, dict):
        raise EvalCaseError(f"bad-case {case_id} 的 rubric 必须是 object")
    allowed = {"must_include", "must_not_contain"}
    if not set(rubric).intersection(allowed):
        raise EvalCaseError(f"bad-case {case_id} 的 rubric 不能为空")
    clean_rubric: dict[str, list[str]] = {}
    for key in allowed:
        values = rubric.get(key, [])
        if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
            raise EvalCaseError(f"bad-case {case_id} 的 rubric.{key} 必须是非空字符串列表")
        if values:
            clean_rubric[key] = values
    if not clean_rubric:
        raise EvalCaseError(f"bad-case {case_id} 的 rubric 不能为空")
    normalized["rubric"] = clean_rubric
    return normalized


def load_offline_observations(eval_dir: Path = EVAL_DIR) -> dict[str, dict[str, Any]]:
    observations: dict[str, dict[str, Any]] = {}
    fixtures_dir = eval_dir / "fixtures"
    if not fixtures_dir.exists():
        return observations
    for fixture in sorted(fixtures_dir.glob("*.json")):
        data = json.loads(fixture.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise EvalCaseError(f"fixture {fixture.name} 必须是 object")
        observations.update(data)
    return observations


# ── Real collection boundary ────────────────────────────────────────────────


def _git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def build_experiment_metadata(
    *, dataset_version: str = DATASET_VERSION, model_provider: str | None = None,
    model_identifier: str | None = None, prompt_template: str = "careercrew-real-eval-v1",
    prompt_version: str = DEFAULT_PROMPT_VERSION, temperature: float = 0,
) -> dict[str, Any]:
    """Emit invariant identifiers only; prompts, questions, and keys are excluded."""
    return {
        "run_id": str(uuid.uuid4()),
        "code_sha": _git_sha(),
        "dataset_version": dataset_version,
        "model_provider": model_provider,
        "model_identifier": model_identifier,
        "prompt_version": prompt_version,
        "prompt_hash": hashlib.sha256(prompt_template.encode("utf-8")).hexdigest()[:16],
        "temperature": temperature,
        "collected_at": datetime.now(UTC).isoformat(),
    }


def _response_content(response: Any) -> str:
    content = getattr(response, "content", response)
    return content if isinstance(content, str) else str(content)


def _extract_json_object(content: str) -> dict[str, Any]:
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end < start:
        raise EvalCaseError("模型没有返回结构化评测观测")
    try:
        parsed = json.loads(content[start:end + 1])
    except json.JSONDecodeError as exc:
        raise EvalCaseError("模型返回的评测观测 JSON 无效") from exc
    if not isinstance(parsed, dict):
        raise EvalCaseError("模型评测观测必须是 object")
    return parsed


def _real_prompt(case: dict[str, Any], *, prompt_version: str = DEFAULT_PROMPT_VERSION) -> str:
    instructions = {
        "route": '将问题路由到一个顾问。只输出 JSON：{"route":"顾问ID"}。',
        "retrieval": '仅输出实际可验证的文档 ID。只输出 JSON：{"retrieved":["doc-id"]}；未知时给空数组。',
        "citation": '直接回答问题并只输出 JSON：{"answer":"回答"}。',
        "tool": '只输出实际需要调用的工具 ID。只输出 JSON：{"tools":["tool-id"]}；不需要时为空数组。',
        "memory": '直接回答问题并只输出 JSON：{"answer":"回答","memory_hit":true 或 false}。',
        "consult": '选择实际应参与会诊的顾问。只输出 JSON：{"agents":["advisor-id"]}。',
    }
    return f"评测提示版本：{prompt_version}\n{instructions[case['kind']]}\n用户问题：{case['question']}"


def default_real_adapter(case: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    """Lazy production adapter; no heavyweight/config import is needed offline."""
    try:
        from careercrew_ai.llm import create_llm
        from careercrew_core.state.settings import SettingsError, load_settings
    except ImportError as exc:
        raise EvalInfrastructureError("dependency", "real evaluation dependency unavailable") from exc
    try:
        settings = load_settings()
    except SettingsError as exc:
        raise EvalInfrastructureError("configuration", "real evaluation settings unavailable") from exc
    prompt_version = str(metadata.get("prompt_version") or DEFAULT_PROMPT_VERSION)
    requested_model = str(metadata.get("model_override") or "").strip()
    temperature = float(metadata.get("temperature") or 0)
    metadata.update({
        "model_provider": settings.llm.provider,
        "model_identifier": requested_model or settings.llm.model,
        "temperature": temperature,
        "prompt_hash": hashlib.sha256(
            _real_prompt({**case, "question": "<redacted>"}, prompt_version=prompt_version).encode("utf-8")
        ).hexdigest()[:16],
    })
    try:
        response = create_llm(
            settings,
            temperature=temperature,
            model=requested_model or None,
        ).invoke(_real_prompt(case, prompt_version=prompt_version))
    except ImportError as exc:
        raise EvalInfrastructureError("dependency", "real evaluation provider dependency unavailable") from exc
    except Exception as exc:
        raise EvalInfrastructureError("provider", "real evaluation provider request failed") from exc
    observation = _extract_json_object(_response_content(response))
    usage = getattr(response, "usage_metadata", None) or getattr(response, "response_metadata", {}).get("usage", {})
    if isinstance(usage, dict):
        total = usage.get("total_tokens") or usage.get("total_token_count")
        if isinstance(total, (int, float)):
            observation["tokens"] = total
    return observation


def collect_real(
    case: dict[str, Any], adapter: RealEvalAdapter | None = None, metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect one actual observation through an injectable adapter boundary."""
    started = time.perf_counter()
    observation = (adapter or default_real_adapter)(case, metadata if metadata is not None else {})
    if not isinstance(observation, dict):
        raise EvalCaseError(f"case {_case_id(case)} 的 adapter 观测必须是 object")
    normalized = dict(observation)
    normalized.setdefault("latency_s", time.perf_counter() - started)
    if normalized.get("tokens") is not None and not isinstance(normalized["tokens"], (int, float)):
        raise EvalCaseError(f"case {_case_id(case)} 的 tokens 必须是数字")
    if not isinstance(normalized.get("latency_s"), (int, float)):
        raise EvalCaseError(f"case {_case_id(case)} 的 latency_s 必须是数字")
    return normalized


def collect_real_observations(
    cases: list[dict[str, Any]], metadata: dict[str, Any], adapter: RealEvalAdapter | None = None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    observations: dict[str, dict[str, Any]] = {}
    case_reports: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for case in cases:
        case_id = _case_id(case)
        try:
            observation = collect_real(case, adapter=adapter, metadata=metadata)
        except EvalInfrastructureError as exc:
            errors.append({"case_id": case_id, "kind": case["kind"], "error_code": exc.category})
            case_reports.append({"case_id": case_id, "kind": case["kind"], "latency_s": None, "tokens": None, "error_code": exc.category})
        except EvalCaseError:
            errors.append({"case_id": case_id, "kind": case["kind"], "error_code": "case"})
            case_reports.append({"case_id": case_id, "kind": case["kind"], "latency_s": None, "tokens": None, "error_code": "case"})
        except Exception:
            # An injected adapter must not turn a release gate into an
            # unstructured traceback. Keep the report safe and fail closed.
            errors.append({"case_id": case_id, "kind": case["kind"], "error_code": "adapter"})
            case_reports.append({"case_id": case_id, "kind": case["kind"], "latency_s": None, "tokens": None, "error_code": "adapter"})
        else:
            observations[case_id] = observation
            case_reports.append({"case_id": case_id, "kind": case["kind"], "latency_s": observation.get("latency_s"), "tokens": observation.get("tokens"), "error_code": None})
    return observations, case_reports, errors


# ── Aggregation and strict case checks ──────────────────────────────────────


def compute_metrics(cases: list[dict[str, Any]], obs: dict[str, dict[str, Any]]) -> dict[str, float]:
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        by_kind.setdefault(case["kind"], []).append(case)

    def observation(case: dict[str, Any]) -> dict[str, Any]:
        case_id = _case_id(case)
        if case_id not in obs:
            raise KeyError(f"case {case_id} 缺少观测值（fixtures 或 --real）")
        return obs[case_id]

    metrics: dict[str, float] = {}
    route_cases = by_kind.get("route", [])
    if route_cases:
        metrics["route_accuracy"] = route_accuracy([observation(case).get("route", "") for case in route_cases], [case["expected"]["route"] for case in route_cases])
    retrieval_cases = by_kind.get("retrieval", [])
    if retrieval_cases:
        metrics["hit_at_5"] = hit_at_k([observation(case).get("retrieved", []) for case in retrieval_cases], [case["expected"]["doc_ids"] for case in retrieval_cases], max((case["expected"].get("k", 5) for case in retrieval_cases), default=5))
        metrics["mrr"] = mrr([observation(case).get("retrieved", []) for case in retrieval_cases], [case["expected"]["doc_ids"] for case in retrieval_cases])
    citation_cases = by_kind.get("citation", [])
    if citation_cases:
        metrics["citation_coverage"] = sum(citation_coverage(observation(case).get("answer", ""), case["expected"]["must_include"]) for case in citation_cases) / len(citation_cases)
    tool_cases = by_kind.get("tool", [])
    if tool_cases:
        metrics["tool_success"] = tool_success([observation(case).get("tools", []) for case in tool_cases], [case["expected"]["tool_names"] for case in tool_cases])
    memory_cases = by_kind.get("memory", [])
    if memory_cases:
        metrics["memory_hit"] = sum(1.0 if bool(observation(case).get("memory_hit")) == bool(case["expected"].get("memory_hit")) else 0.0 for case in memory_cases) / len(memory_cases)
        metrics["retention"] = sum(retention(observation(case).get("answer", ""), case["expected"].get("retention_ref", [])) for case in memory_cases) / len(memory_cases)
    consult_cases = by_kind.get("consult", [])
    if consult_cases:
        metrics["consult_agent_coverage"] = sum(1.0 if all(agent in observation(case).get("agents", []) for agent in case["expected"]["expected_agents"]) else 0.0 for case in consult_cases) / len(consult_cases)
        metrics["consult_avg_latency_s"] = sum(float(observation(case).get("latency_s") or 0.0) for case in consult_cases) / len(consult_cases)
        metrics["consult_avg_tokens"] = sum(float(observation(case).get("tokens") or 0.0) for case in consult_cases) / len(consult_cases)
    return metrics


def check_consult_bounds(cases: list[dict[str, Any]], obs: dict[str, dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for case in cases:
        if case["kind"] != "consult":
            continue
        case_id, expected, observation = _case_id(case), case["expected"], obs.get(_case_id(case), {})
        for field in ("latency_s", "tokens"):
            limit = expected.get(f"max_{field}")
            if limit is None:
                continue
            value = observation.get(field)
            if not isinstance(value, (int, float)):
                failures.append(f"{case_id}: missing {field} for max_{field} {float(limit):.3f}")
            elif value > limit:
                value_text = f"{float(value):.3f}" if field == "latency_s" else f"{value:g}"
                limit_text = f"{float(limit):.3f}" if field == "latency_s" else f"{limit:g}"
                failures.append(f"{case_id}: {field} {value_text} > max_{field} {limit_text}")
    return failures


def case_passes(obs: dict[str, Any], rubric: dict[str, list[str]]) -> bool:
    answer = obs.get("answer", "") or ""
    return all(term in answer for term in rubric.get("must_include", [])) and all(term not in answer for term in rubric.get("must_not_contain", []))


def bad_case_pass_rate(cases: list[dict[str, Any]], obs: dict[str, dict[str, Any]]) -> float:
    if not cases:
        return 1.0
    return sum(case_passes(obs.get(_case_id(case), {}), case["rubric"]) for case in cases) / len(cases)


def required_case_failures(cases: list[dict[str, Any]], obs: dict[str, dict[str, Any]]) -> list[str]:
    failures = check_consult_bounds(cases, obs)
    for case in cases:
        case_id, expected, observation = _case_id(case), case["expected"], obs.get(_case_id(case))
        if observation is None:
            failures.append(f"{case_id}: missing observation")
            continue
        if case["kind"] == "route" and observation.get("route") != expected.get("route"):
            failures.append(f"{case_id}: route mismatch")
        elif case["kind"] == "retrieval" and not any(doc_id in observation.get("retrieved", []) for doc_id in expected.get("doc_ids", [])):
            failures.append(f"{case_id}: retrieval miss")
        elif case["kind"] == "citation" and citation_coverage(observation.get("answer", ""), expected.get("must_include", [])) < 1:
            failures.append(f"{case_id}: citation rubric failed")
        elif case["kind"] == "tool" and not all(tool in observation.get("tools", []) for tool in expected.get("tool_names", [])):
            failures.append(f"{case_id}: tool expectation failed")
        elif case["kind"] == "memory" and (bool(observation.get("memory_hit")) != bool(expected.get("memory_hit")) or retention(observation.get("answer", ""), expected.get("retention_ref", [])) < 1):
            failures.append(f"{case_id}: memory expectation failed")
        elif case["kind"] == "consult" and not all(agent in observation.get("agents", []) for agent in expected.get("expected_agents", [])):
            failures.append(f"{case_id}: consult agent expectation failed")
    return failures


# ── Baseline gates ──────────────────────────────────────────────────────────


def compare_baseline(metrics: dict[str, float], baseline: dict[str, float]) -> list[str]:
    regressions = []
    for key, base in baseline.items():
        if key not in metrics:
            regressions.append(f"{key}: 缺失（基线 {base}）")
        elif key not in {"consult_avg_latency_s", "consult_avg_tokens"} and metrics[key] < base - REGRESSION_TOLERANCE:
            regressions.append(f"{key}: {metrics[key]} < 基线 {base}")
    return regressions


BAD_CASE_DROP_LIMIT = 0.02
RELEASE_GATE = {"bad_case_pass_rate": ("drop", BAD_CASE_DROP_LIMIT), "route_accuracy": ("drop", 0.01), "citation_coverage": ("drop", 0.03), "tool_success": ("drop", 0.01), "consult_avg_latency_s": ("rise", 0.20), "consult_avg_tokens": ("rise", 0.25)}


def gate_regressions(metrics: dict[str, float], baseline: dict[str, float]) -> list[str]:
    failures = []
    for key, (direction, tolerance) in RELEASE_GATE.items():
        if key not in metrics or key not in baseline or baseline[key] == 0:
            continue
        ratio = metrics[key] / baseline[key]
        if direction == "drop" and ratio < 1 - tolerance:
            failures.append(f"{key}: {metrics[key]:.4f} vs 基线 {baseline[key]:.4f}（相对下降 {(1 - ratio):.1%} > {tolerance:.0%}）")
        elif direction == "rise" and ratio > 1 + tolerance:
            failures.append(f"{key}: {metrics[key]:.4f} vs 基线 {baseline[key]:.4f}（相对上升 {(ratio - 1):.1%} > {tolerance:.0%}）")
    return failures


def _write_report(path: str, *, status: str, metadata: dict[str, Any], metrics: dict[str, float] | None = None, cases: list[dict[str, Any]] | None = None, errors: list[dict[str, str]] | None = None) -> None:
    if not path:
        return
    payload: dict[str, Any] = dict(metrics or {})
    payload.update({"status": status, "metadata": metadata, "metrics": metrics or {}, "cases": cases or [], "errors": errors or []})
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CareerCrew Agent/RAG evaluation runner")
    parser.add_argument("--offline", action="store_true", help="use checked-in fixture observations")
    parser.add_argument("--real", action="store_true", help="collect actual observations through the configured LLM")
    parser.add_argument("--require-real", action="store_true", help="fail for unavailable real infrastructure or required case failures")
    parser.add_argument("--allow-skip", action="store_true", help="only configuration/dependency-unavailable real runs may exit zero")
    parser.add_argument("--model", default="", help="optional configured model override for real evaluation")
    parser.add_argument("--prompt-version", default=DEFAULT_PROMPT_VERSION, help="prompt variant identifier recorded in the experiment")
    parser.add_argument("--temperature", type=float, default=0, help="real-evaluation temperature (default: 0)")
    parser.add_argument("--bad-cases", default="", help="promoted bad-case JSONL path")
    parser.add_argument("--update-baseline", action="store_true", help="write metrics to the offline baseline")
    parser.add_argument("--compare", default="", help="baseline file path")
    parser.add_argument("--fail-on-regression", action="store_true", help="nonzero exit for baseline regressions")
    parser.add_argument("--report", default="", help="safe JSON experiment report path")
    args = parser.parse_args(argv)
    if args.offline == args.real:
        parser.error("必须且只能指定 --offline 或 --real")
    if (args.require_real or args.allow_skip) and not args.real:
        parser.error("--require-real/--allow-skip 只能与 --real 一起使用")
    if args.require_real and args.allow_skip:
        parser.error("--require-real 与 --allow-skip 不能同时使用")
    if not 0 <= args.temperature <= 2:
        parser.error("--temperature 必须在 0 到 2 之间")
    metadata = build_experiment_metadata(
        model_identifier=args.model.strip() or None,
        prompt_version=args.prompt_version.strip() or DEFAULT_PROMPT_VERSION,
        temperature=args.temperature,
    )
    if args.model.strip():
        metadata["model_override"] = args.model.strip()
    try:
        cases = load_cases()
        bad_case_cases = load_cases(Path(args.bad_cases), bad_cases=True) if args.bad_cases else []
        duplicate_ids = {case["case_id"] for case in cases} & {case["case_id"] for case in bad_case_cases}
        if duplicate_ids:
            raise EvalCaseError(f"评测 case_id 与 bad-case 重复: {sorted(duplicate_ids)!r}")
    except EvalCaseError as exc:
        print(f"评测数据无效: {exc}")
        _write_report(args.report, status="failed", metadata=metadata, errors=[{"error_code": "case"}])
        return 2
    if not cases and not bad_case_cases:
        print("data/eval/cases.jsonl 为空或不存在")
        _write_report(args.report, status="failed", metadata=metadata, errors=[{"error_code": "case"}])
        return 2
    case_reports: list[dict[str, Any]] = []
    if args.offline:
        try:
            observations = load_offline_observations()
        except (json.JSONDecodeError, EvalCaseError):
            print("离线 fixtures 无效")
            _write_report(args.report, status="failed", metadata=metadata, errors=[{"error_code": "case"}])
            return 2
        for case in cases + bad_case_cases:
            observation = observations.get(_case_id(case), {})
            case_reports.append({"case_id": _case_id(case), "kind": case["kind"], "latency_s": observation.get("latency_s"), "tokens": observation.get("tokens"), "error_code": None})
    else:
        observations, case_reports, collection_errors = collect_real_observations(cases + bad_case_cases, metadata)
        if collection_errors:
            skippable = all(error["error_code"] in {"configuration", "dependency"} for error in collection_errors)
            if args.allow_skip and not args.require_real and skippable:
                print("[real eval skipped] real environment unavailable")
                _write_report(args.report, status="skipped", metadata=metadata, cases=case_reports, errors=collection_errors)
                return 0
            print("真实评测采集失败: " + ", ".join(sorted({error["error_code"] for error in collection_errors})))
            _write_report(args.report, status="failed", metadata=metadata, cases=case_reports, errors=collection_errors)
            return 2 if skippable else 1
    try:
        metrics = compute_metrics(cases, observations)
    except (KeyError, TypeError, ValueError) as exc:
        print(f"评测观测无效: {exc}")
        _write_report(args.report, status="failed", metadata=metadata, cases=case_reports, errors=[{"error_code": "case"}])
        return 1
    if bad_case_cases:
        metrics["bad_case_pass_rate"] = bad_case_pass_rate(bad_case_cases, observations)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    if args.update_baseline:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"baseline 已更新: {BASELINE_PATH}")
    failures: list[str] = []
    if args.real and args.require_real:
        failures.extend(required_case_failures(cases, observations))
        failures.extend(f"{_case_id(case)}: bad-case rubric failed" for case in bad_case_cases if not case_passes(observations.get(_case_id(case), {}), case["rubric"]))
    if args.compare:
        baseline = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        regressions = compare_baseline(metrics, baseline) + gate_regressions(metrics, baseline)
        if regressions:
            print("回归:")
            for regression in regressions:
                print(f"  - {regression}")
            if args.fail_on_regression:
                failures.extend(regressions)
        else:
            print("无回归（全部指标在基线与发布阈值内）")
    if failures:
        print("评测未通过:")
        for failure in failures:
            print(f"  - {failure}")
        _write_report(args.report, status="failed", metadata=metadata, metrics=metrics, cases=case_reports, errors=[{"error_code": "regression"}])
        return 1
    _write_report(args.report, status="completed", metadata=metadata, metrics=metrics, cases=case_reports)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
