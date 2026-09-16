"""Versioned offline and real-model evaluation with strict release semantics.

Offline observations are checked-in fixtures. Real observations always cross the
configured LLM boundary; unavailable infrastructure is never reported as a pass.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EVAL_DIR = Path(__file__).resolve().parents[1] / "data" / "eval"
CASES_PATH = EVAL_DIR / "cases.jsonl"
BASELINE_PATH = EVAL_DIR / "baseline.json"
REGRESSION_TOLERANCE = 0.01
DATASET_VERSION = "2026-09-10.v1"
DEFAULT_PROMPT_VERSION = "careercrew-real-eval-v1"
SUPPORTED_KINDS = {"route", "retrieval", "citation", "tool", "memory", "consult"}
RealEvalAdapter = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
RUNTIME_EVAL_MARKER = "CAREERCREW_EVAL_RUNTIME"
RUNTIME_EVAL_USER_ID = "CAREERCREW_EVAL_USER_ID"
RUNTIME_EVAL_RUN_ID = "CAREERCREW_EVAL_RUN_ID"
RUNTIME_EVAL_TENANT_ATTESTATION = "CAREERCREW_EVAL_TENANT_ATTESTATION"
RUNTIME_EVAL_TENANT_ATTESTATION_URL = "CAREERCREW_EVAL_TENANT_ATTESTATION_URL"
RUNTIME_EVAL_TENANT_ATTESTATION_TOKEN = "CAREERCREW_EVAL_TENANT_ATTESTATION_TOKEN"
RUNTIME_EVAL_TENANT_ATTESTATION_NONCE = "CAREERCREW_EVAL_TENANT_ATTESTATION_NONCE"
RUNTIME_EVAL_PROFILE = "CAREERCREW_EVAL_PROFILE"
_RUNTIME_USER_PATTERN = re.compile(r"^eval_[A-Za-z0-9][A-Za-z0-9_-]{2,62}$")
_RUNTIME_RUN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,62}$")
_RUNTIME_NONCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$")
PROMPT_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


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
    prompt_version = validate_prompt_version(prompt_version)
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


def validate_prompt_version(value: str | None) -> str:
    """Keep the prompt variant an identifier, never a prompt fragment."""

    normalized = str(value or "").strip()
    if not normalized:
        return DEFAULT_PROMPT_VERSION
    if not PROMPT_VERSION_PATTERN.fullmatch(normalized):
        raise EvalCaseError(
            "prompt_version 必须是 1-64 位字母、数字、点、下划线或连字符标识"
        )
    return normalized


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
    prompt_version = validate_prompt_version(prompt_version)
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


def _validate_tenant_attestation_url(value: str) -> str:
    url = str(value or "").strip()
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise EvalInfrastructureError("configuration", "external tenant attestation URL is invalid") from exc
    if port is not None and not 1 <= port <= 65535:
        raise EvalInfrastructureError("configuration", "external tenant attestation URL has an invalid port")
    if parsed.scheme != "https" or not parsed.netloc or not host or parsed.username or parsed.password:
        raise EvalInfrastructureError(
            "configuration", "external tenant attestation URL must be an HTTPS URL without credentials",
        )
    normalized_host = host.lower().strip("[]").rstrip(".")
    if normalized_host == "localhost":
        raise EvalInfrastructureError("configuration", "external tenant attestation URL cannot be loopback")
    try:
        address = ipaddress.ip_address(normalized_host)
    except ValueError:
        address = None
    mapped = getattr(address, "ipv4_mapped", None) if address is not None else None
    if address is not None and (
        address.is_loopback
        or address.is_unspecified
        or address.is_link_local
        or (mapped is not None and mapped.is_loopback)
    ):
        raise EvalInfrastructureError("configuration", "external tenant attestation URL cannot be loopback")
    return url.rstrip("/")


def verify_runtime_eval_tenant_attestation(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Verify the eval tenant with the protected provisioning authority."""

    env = os.environ if environ is None else environ
    verifier_url = _validate_tenant_attestation_url(
        str(env.get(RUNTIME_EVAL_TENANT_ATTESTATION_URL, "")).strip()
    )
    token = str(env.get(RUNTIME_EVAL_TENANT_ATTESTATION_TOKEN, "")).strip()
    nonce = str(env.get(RUNTIME_EVAL_TENANT_ATTESTATION_NONCE, "")).strip()
    if not token:
        raise EvalInfrastructureError("configuration", "external tenant attestation token is required")
    if not _RUNTIME_NONCE_PATTERN.fullmatch(nonce):
        raise EvalInfrastructureError("configuration", "external tenant attestation nonce is invalid")
    user_id = str(env.get(RUNTIME_EVAL_USER_ID, "")).strip()
    run_id = str(env.get(RUNTIME_EVAL_RUN_ID, "")).strip()
    from scripts.deployment_identity import deployment_identity

    try:
        deployment = deployment_identity(env.get("DATABASE_URL", ""), env.get("QDRANT_URL", ""), environ=env)
    except ValueError as exc:
        raise EvalInfrastructureError("configuration", "external tenant deployment is invalid") from exc
    payload = {
        "contract": "careercrew-eval-tenant-v1",
        "user_id": user_id,
        "run_id": run_id,
        "nonce": nonce,
        "deployment": deployment,
    }
    try:
        response = requests.post(
            verifier_url,
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=20,
        )
        response.raise_for_status()
        receipt = response.json()
    except (OSError, requests.RequestException, ValueError) as exc:
        raise EvalInfrastructureError(
            "configuration", "external tenant attestation request failed",
        ) from exc
    if not isinstance(receipt, dict):
        raise EvalInfrastructureError("configuration", "external tenant attestation receipt is invalid")
    if receipt.get("deployment") != deployment:
        raise EvalInfrastructureError("configuration", "external tenant deployment mismatch")
    if (
        receipt.get("status") != "provisioned"
        or receipt.get("user_id") != user_id
        or receipt.get("run_id") != run_id
        or receipt.get("tenant_id") != user_id
        or receipt.get("nonce") != nonce
    ):
        raise EvalInfrastructureError(
            "configuration", "external tenant attestation receipt does not match scope or nonce",
        )
    expires_at = receipt.get("expires_at")
    if not isinstance(expires_at, str) or not expires_at.strip():
        raise EvalInfrastructureError("configuration", "external tenant attestation receipt has no expiry")
    try:
        expiry = datetime.fromisoformat(expires_at.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvalInfrastructureError("configuration", "external tenant attestation expiry is invalid") from exc
    if expiry.tzinfo is None or expiry.astimezone(UTC) <= datetime.now(UTC):
        raise EvalInfrastructureError("configuration", "external tenant attestation has expired")
    attestation_id = str(receipt.get("attestation_id") or "").strip()
    if not attestation_id or len(attestation_id) > 128:
        raise EvalInfrastructureError("configuration", "external tenant attestation id is missing")
    return {"attestation_id": attestation_id, "expires_at": expiry.astimezone(UTC).isoformat()}


def validate_runtime_eval_environment(
    environ: Mapping[str, str] | None = None,
    *,
    require_remote_attestation: bool = False,
) -> str:
    """Require an explicit, isolated tenant before touching the live runtime.

    The old direct provider probe remains available only as ``--model-probe``.
    A protected evaluation must opt into the product runtime and use a
    dedicated ``eval_`` tenant so the evaluator cannot silently run against a
    normal account or mistake a prompt-only response for product evidence.
    """

    env = os.environ if environ is None else environ
    if str(env.get(RUNTIME_EVAL_MARKER, "")).strip() != "1":
        raise EvalInfrastructureError(
            "configuration",
            f"{RUNTIME_EVAL_MARKER}=1 is required for product-runtime evaluation",
        )
    user_id = str(env.get(RUNTIME_EVAL_USER_ID, "")).strip()
    if not _RUNTIME_USER_PATTERN.fullmatch(user_id):
        raise EvalInfrastructureError(
            "configuration",
            f"{RUNTIME_EVAL_USER_ID} must be a dedicated eval_ tenant",
        )
    run_id = str(env.get(RUNTIME_EVAL_RUN_ID, "")).strip()
    if not _RUNTIME_RUN_PATTERN.fullmatch(run_id):
        raise EvalInfrastructureError(
            "configuration",
            f"{RUNTIME_EVAL_RUN_ID} must be a unique protected run identifier",
        )
    if user_id != f"eval_{run_id}":
        raise EvalInfrastructureError(
            "configuration",
            f"{RUNTIME_EVAL_USER_ID} must be scoped to {RUNTIME_EVAL_RUN_ID}",
        )
    attestation = str(env.get(RUNTIME_EVAL_TENANT_ATTESTATION, "")).strip()
    expected = f"{user_id}:{run_id}:provisioned"
    if attestation != expected:
        raise EvalInfrastructureError(
            "configuration",
            f"tenant attestation ({RUNTIME_EVAL_TENANT_ATTESTATION}) must attest the provisioned eval tenant",
        )
    if require_remote_attestation:
        try:
            verify_runtime_eval_tenant_attestation(env)
        except EvalInfrastructureError as exc:
            raise EvalInfrastructureError(
                exc.category,
                f"external tenant attestation failed: {exc}",
            ) from exc
    return user_id


def _runtime_profile(environ: Mapping[str, str]) -> str:
    """Return synthetic evaluation profile text without putting it in reports."""

    configured = str(environ.get(RUNTIME_EVAL_PROFILE, "")).strip()
    if configured:
        return configured[:4000]
    return (
        "当前职位：后端开发；工作年限：3年；核心技能：Python、RAG；"
        "目标方向：大模型工程师；期望城市：上海"
    )


class RuntimeEvalSession:
    """Run cases through CareerCrew's real runtime and clean its eval scope."""

    def __init__(
        self,
        metadata: dict[str, Any],
        *,
        environ: Mapping[str, str] | None = None,
        runtime_factory: Callable[[], Any] | None = None,
        require_remote_attestation: bool = False,
    ) -> None:
        self.environ = dict(os.environ if environ is None else environ)
        self.user_id = validate_runtime_eval_environment(
            self.environ,
            require_remote_attestation=require_remote_attestation,
        )
        self.eval_run_id = self.environ[RUNTIME_EVAL_RUN_ID].strip()
        self.metadata = metadata
        self.profile = _runtime_profile(self.environ)
        self._created_threads: list[str] = []
        self._cleanup_failures: dict[str, tuple[str, ...]] = {}
        self._memory_cleaned = False
        if runtime_factory is None or require_remote_attestation:
            # Resolve configuration before constructing any write-capable store.
            # An injected adapter is diagnostic only, never protected evidence.
            if self.environ.get("DATABASE_URL") and self.environ.get("QDRANT_URL"):
                from careercrew_core.state.settings import load_settings
                from scripts.deployment_identity import deployment_identity

                try:
                    expected = deployment_identity(
                        self.environ["DATABASE_URL"], self.environ["QDRANT_URL"],
                        environ=self.environ,
                    )
                    resolved = load_settings()
                    actual = deployment_identity(
                        resolved.memory.postgres.dsn, resolved.vector_store.url,
                    )
                except Exception as exc:
                    raise EvalInfrastructureError(
                        "configuration", "resolved runtime deployment could not be validated",
                    ) from exc
                if actual != expected:
                    raise EvalInfrastructureError("configuration", "resolved runtime deployment mismatch")
            # The current runtime has no exclusive writer lease or worker-free
            # initialization contract. Tenant naming/remote provisioning alone
            # cannot guarantee that an already claimed worker will not upsert
            # after cleanup. Keep all live execution closed until that contract
            # is implemented and verified; do not label this as robust fencing.
            raise EvalInfrastructureError(
                "isolation", "live runtime worker lifecycle isolation is not guaranteed",
            )
        try:
            self.runtime = runtime_factory()
            self.runtime._ensure_heavy()
        except EvalInfrastructureError:
            raise
        except ImportError as exc:
            raise EvalInfrastructureError(
                "dependency", "CareerCrew product runtime dependencies unavailable"
            ) from exc
        except Exception as exc:
            # Do not expose DSNs, provider responses, or prompt text in the
            # experiment report. The caller records only this stable category.
            raise EvalInfrastructureError(
                "runtime", "CareerCrew product runtime could not initialize"
            ) from exc

        settings = getattr(self.runtime, "settings", None)
        llm_settings = getattr(settings, "llm", None)
        provider = str(getattr(llm_settings, "provider", "") or "").strip()
        model = str(getattr(llm_settings, "model", "") or "").strip()
        if provider:
            self.metadata["model_provider"] = provider
        if model:
            self.metadata["model_identifier"] = model
        self.metadata.update({
            "evaluation_mode": "product_runtime",
            "runtime_contract_version": "careercrew-runtime-eval-v1",
            "runtime_user_scope": "dedicated_eval_tenant",
            "runtime_eval_run_id": self.eval_run_id,
            "runtime_tenant_attestation": (
                "externally_verified" if require_remote_attestation else "provisioned"
            ),
        })

    def __enter__(self) -> RuntimeEvalSession:
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> bool:
        self.close()
        return False

    def close(self) -> None:
        """Retry scoped cleanup and fail if protected data may be left behind."""

        for thread_id in list(self._created_threads):
            self._cleanup_thread(thread_id)
        self._cleanup_memory()
        if self._cleanup_failures:
            raise EvalInfrastructureError(
                "cleanup", "runtime evaluation cleanup did not complete"
            )

    def _cleanup_memory(self) -> None:
        """Delete eval vectors and memory rows without exposing account purge APIs."""

        if self._memory_cleaned:
            return
        memory_service = getattr(self.runtime, "memory_service", None)
        if memory_service is None:
            # Test doubles and a future runtime without long-term memory have
            # nothing to clean. Product runtime always has this service after
            # _ensure_heavy().
            self._memory_cleaned = True
            return

        errors: list[str] = []
        stores: list[Any] = []
        seen_store_ids: set[int] = set()
        for store in (
            getattr(memory_service, "_vector_store", None),
            getattr(self.runtime, "_episodic_vector_store", None),
        ):
            if store is None or id(store) in seen_store_ids:
                continue
            seen_store_ids.add(id(store))
            stores.append(store)
        for store in stores:
            delete_by_metadata = getattr(store, "delete_by_metadata", None)
            metadata_exists = getattr(store, "metadata_exists", None)
            if not callable(delete_by_metadata) or not callable(metadata_exists):
                errors.append("vector_contract")
                continue
            try:
                delete_by_metadata({"user_id": self.user_id})
                if metadata_exists({"user_id": self.user_id}):
                    errors.append("vector_residual")
            except Exception:
                errors.append("vector")

        repository = getattr(memory_service, "records", None)
        cleanup = getattr(repository, "cleanup_eval_tenant", None)
        summaries: list[dict[str, Any]] = []
        if callable(cleanup):
            try:
                first_summary = cleanup(self.user_id)
                if isinstance(first_summary, dict):
                    summaries.append(first_summary)
            except Exception:
                errors.append("repository")
        else:
            errors.append("repository_contract")

        # Recheck residual active records/outbox rows. Repeated sweeps do not
        # fence a worker that already fetched a record or is still embedding.
        if callable(cleanup):
            try:
                final_summary = cleanup(self.user_id)
                if isinstance(final_summary, dict):
                    summaries.append(final_summary)
                    if any(
                        int(final_summary.get(key, 0) or 0) > 0
                        for key in ("outbox_remaining", "records_remaining")
                    ):
                        errors.append("repository_residual")
            except Exception:
                errors.append("repository_final_sweep")

        # Observe vectors again after the DB sweeps. A late upsert is a failure,
        # not proof that repeating deletion would establish exclusive ownership.
        for store in stores:
            try:
                if store.metadata_exists({"user_id": self.user_id}):
                    errors.append("vector_residual_after_database")
            except Exception:
                errors.append("vector_final_verification")

        if summaries:
            summary = dict(summaries[0])
            for key in ("outbox_remaining", "records_remaining"):
                if key in summaries[-1]:
                    summary[key] = summaries[-1][key]
            self.metadata["runtime_cleanup"] = {
                key: int(value) for key, value in summary.items()
                if isinstance(value, int) and not isinstance(value, bool)
            }
        if errors:
            self._cleanup_failures["__eval_memory__"] = tuple(sorted(set(errors)))
            return
        self._memory_cleaned = True
        self._cleanup_failures.pop("__eval_memory__", None)

    def _new_thread(self) -> str:
        thread_id = str(uuid.uuid4())
        self._created_threads.append(thread_id)
        return thread_id

    def _cleanup_thread(self, thread_id: str) -> None:
        """Delete one generated thread; never use the account-wide purge API."""

        errors: list[str] = []
        conversation_store = getattr(self.runtime, "conversation_store", None)
        if conversation_store is not None:
            try:
                conversation_store.delete_conversation(thread_id, self.user_id)
                get_conversation = getattr(conversation_store, "get_conversation", None)
                if callable(get_conversation) and get_conversation(thread_id, self.user_id) is not None:
                    errors.append("conversation_residual")
            except Exception:
                errors.append("conversation")

        thread_store = getattr(self.runtime, "thread_store", None)
        if thread_store is not None:
            try:
                thread_store.delete_all_for_thread(self.user_id, thread_id)
                get_thread = getattr(thread_store, "get", None)
                if callable(get_thread) and get_thread(self.user_id, thread_id) is not None:
                    errors.append("thread_residual")
            except Exception:
                errors.append("thread")

        cycles = getattr(self.runtime, "_cycles", None)
        cycle_lock = getattr(self.runtime, "_cycles_lock", None)
        try:
            if cycle_lock is not None:
                with cycle_lock:
                    cycles.pop((self.user_id, thread_id), None)
            elif isinstance(cycles, dict):
                cycles.pop((self.user_id, thread_id), None)
        except Exception:
            errors.append("cycle")

        if errors:
            self._cleanup_failures[thread_id] = tuple(sorted(set(errors)))
        else:
            self._cleanup_failures.pop(thread_id, None)
            try:
                self._created_threads.remove(thread_id)
            except ValueError:
                pass

    @staticmethod
    def _require_turn(result: Any) -> Any:
        turn = getattr(result, "turn", None)
        if turn is None:
            raise EvalInfrastructureError(
                "runtime", "product runtime did not persist an evaluation turn"
            )
        return turn

    @staticmethod
    def _tokens(result: Any) -> int | float | None:
        total = getattr(result, "total_tokens", None)
        if isinstance(total, (int, float)):
            return total
        input_tokens = getattr(result, "input_tokens", None)
        output_tokens = getattr(result, "output_tokens", None)
        if isinstance(input_tokens, (int, float)) and isinstance(output_tokens, (int, float)):
            return input_tokens + output_tokens
        return None

    def _run_route(self, question: str) -> dict[str, Any]:
        """Use the same orchestrator decision node as the consult product path."""

        from careercrew_core.supervisor.consult_orchestrator import (
            _build_orchestrator_node,
        )

        state = {
            "user_intent": question,
            "user_profile": self.profile,
            "orchestrator_round": 0,
            "total_agent_calls": 0,
            "consult_calls": [],
        }
        decision_node = _build_orchestrator_node(
            self.runtime.llm,
            max_rounds=3,
            max_group_size=3,
            max_total_calls=8,
            emit=None,
        )
        update = decision_node(state)
        agents = update.get("next_agents") or []
        return {"route": str(agents[0]) if agents else ""}

    def _run_knowledge(self, case: dict[str, Any], thread_id: str) -> dict[str, Any]:
        memory_hit: bool | None = None
        if case["kind"] == "memory":
            injector = getattr(self.runtime, "memory_injector", None)
            memory_service = getattr(self.runtime, "memory_service", None)
            if injector is None or memory_service is None:
                raise EvalInfrastructureError("runtime", "memory injector is unavailable")
            try:
                policy = memory_service.effective_policy(self.user_id)
                if not policy.can_use:
                    raise EvalInfrastructureError("configuration", "eval memory policy is disabled")
                # This is the same injector used by BaseAgent before the real
                # knowledge answer. It proves a memory hit without reporting
                # the protected memory contents.
                memory_hit = bool(injector.build(self.user_id, case["question"]))
            except EvalInfrastructureError:
                raise
            except Exception as exc:
                raise EvalInfrastructureError("runtime", "memory observation failed") from exc

        result = self.runtime.run_knowledge_ask_stream(
            case["question"],
            self.user_id,
            thread_id=thread_id,
            category=str(case.get("category") or ""),
            scope=str(case.get("scope") or "all"),
        )
        self._require_turn(result)
        sources = getattr(result, "sources", None) or []
        retrieved = [
            str(source.get("doc") or source.get("document_id"))
            for source in sources
            if isinstance(source, dict) and (source.get("doc") or source.get("document_id"))
        ]
        observation: dict[str, Any] = {
            "answer": str(getattr(result, "content", "") or ""),
            "retrieved": retrieved,
            "tokens": self._tokens(result),
        }
        if memory_hit is not None:
            observation["memory_hit"] = memory_hit
        return observation

    def _run_tool(self, case: dict[str, Any], thread_id: str) -> dict[str, Any]:
        result = self.runtime.run_match_stream(
            thread_id,
            self.user_id,
            case["question"],
        )
        self._require_turn(result)
        tool_calls = getattr(result, "tool_calls", None) or []
        return {
            "tools": [
                str(call.get("tool_name"))
                for call in tool_calls
                if isinstance(call, dict) and call.get("tool_name")
            ],
            "answer": str(getattr(result, "content", "") or ""),
            "tokens": self._tokens(result),
        }

    def _run_consult(self, case: dict[str, Any], thread_id: str) -> dict[str, Any]:
        """Invoke the same automatic fan-out graph used by ``POST /consult``."""

        from langchain_core.messages import HumanMessage

        from careercrew_core.supervisor.consult_orchestrator import (
            build_consult_orchestrator_graph,
            synthesize_fallback,
        )

        effective = self.runtime.compute_effective_tools(
            "consult", None, user_id=self.user_id,
        )
        ctx = self.runtime._begin_chat_turn(
            thread_id,
            self.user_id,
            module="consult",
            agent_id="consult_orchestrator",
            user_text=case["question"],
            effective_tools=effective,
        )
        if ctx is None:
            raise EvalInfrastructureError("runtime", "consult turn could not be persisted")
        finished = False
        try:
            pending_id = self.runtime.record_user_message(
                self.user_id, thread_id, case["question"], module="consult",
            )
            graph = build_consult_orchestrator_graph(
                self.runtime.llm,
                lambda name, cb: self.runtime.new_consult_agent(
                    name,
                    cb,
                    episodic=self.runtime._get_episodic(thread_id, self.user_id),
                    allowed=effective,
                    hitl_requires=self.runtime._hitl_requires(),
                ),
            )
            state = {
                "thread_id": thread_id,
                "user_id": self.user_id,
                "stage": "consult",
                "user_intent": case["question"],
                "messages": [HumanMessage(content=case["question"])],
                "pending_action": None,
                "agent_outputs": {},
                "target_companies": [],
                "synthesis": "",
                "orchestrator_round": 0,
                "total_agent_calls": 0,
                "next_agents": [],
                "agent_tasks": {},
                "consult_calls": [],
                "pending_user_entry_id": pending_id,
                "needs_user_input": False,
                "input_fields": [],
                "user_profile": self.profile,
            }
            result = graph.invoke(state)
            calls = list(result.get("consult_calls") or [])
            agents = list(dict.fromkeys(
                str(call.get("agent"))
                for call in calls
                if isinstance(call, dict) and call.get("agent")
            ))
            opinions = {
                str(call["agent"]): str(call.get("content") or "")
                for call in calls
                if isinstance(call, dict) and call.get("agent")
            }
            final = str(result.get("synthesis") or "").strip()
            if not final:
                final = synthesize_fallback(opinions, case["question"], self.runtime.llm)

            from careercrew_api.runtime import (
                _observability_from_result,
                _rag_query_retrievals,
            )

            tool_calls: list[dict] = []
            retrievals: list[dict] = []
            input_tokens = 0
            output_tokens = 0
            token_count = 0
            for call in calls:
                details = call.get("tool_call_details") or []
                blocked = call.get("blocked_tool_calls") or []
                result_like = type("EvalAgentResult", (), {
                    "input_tokens": call.get("input_tokens"),
                    "output_tokens": call.get("output_tokens"),
                    "tool_call_details": details,
                    "blocked_tool_calls": blocked,
                })()
                observed = _observability_from_result(result_like)
                tool_calls.extend(observed["tool_calls"])
                retrievals.extend(
                    _rag_query_retrievals(details, start_index=len(retrievals))
                )
                if isinstance(call.get("input_tokens"), (int, float)):
                    input_tokens += call["input_tokens"]
                    token_count += 1
                if isinstance(call.get("output_tokens"), (int, float)):
                    output_tokens += call["output_tokens"]
                    token_count += 1
            total_tokens = input_tokens + output_tokens if token_count else None
            self.runtime._finish_chat_turn(
                ctx,
                final,
                metadata={"opinions": opinions},
                input_tokens=input_tokens if token_count else None,
                output_tokens=output_tokens if token_count else None,
                total_tokens=total_tokens,
                retrievals=retrievals or None,
                tool_calls=tool_calls or None,
            )
            finished = True
            return {"agents": agents, "answer": final, "tokens": total_tokens}
        except EvalInfrastructureError:
            if not finished:
                self.runtime._fail_chat_turn(
                    ctx, EvalInfrastructureError("runtime", "consult evaluation failed")
                )
            raise
        except Exception as exc:
            if not finished:
                self.runtime._fail_chat_turn(ctx, exc)
            raise EvalInfrastructureError("runtime", "consult runtime evaluation failed") from exc

    def run_case(self, case: dict[str, Any], _metadata: dict[str, Any]) -> dict[str, Any]:
        kind = case["kind"]
        if kind == "route":
            return self._run_route(case["question"])
        thread_id = self._new_thread()
        try:
            if kind in {"retrieval", "citation", "memory"}:
                return self._run_knowledge(case, thread_id)
            if kind == "tool":
                return self._run_tool(case, thread_id)
            if kind == "consult":
                return self._run_consult(case, thread_id)
            raise EvalCaseError(f"不支持 runtime eval kind: {kind}")
        finally:
            self._cleanup_thread(thread_id)


def collect_runtime_observations(
    cases: list[dict[str, Any]],
    metadata: dict[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
    runtime_factory: Callable[[], Any] | None = None,
    require_remote_attestation: bool = False,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    """Collect protected observations with a dedicated tenant and cleanup gate."""

    try:
        with RuntimeEvalSession(
            metadata,
            environ=environ,
            runtime_factory=runtime_factory,
            require_remote_attestation=require_remote_attestation,
        ) as session:
            return collect_real_observations(cases, metadata, adapter=session.run_case)
    except EvalInfrastructureError as exc:
        error_code = exc.category
        reports = [
            {
                "case_id": _case_id(case),
                "kind": case["kind"],
                "latency_s": None,
                "tokens": None,
                "error_code": error_code,
            }
            for case in cases
        ]
        errors = [
            {"case_id": _case_id(case), "kind": case["kind"], "error_code": error_code}
            for case in cases
        ]
        return {}, reports, errors


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
    parser.add_argument("--real", action="store_true", help="collect actual observations")
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="run cases through the protected CareerCrew product runtime and Qdrant",
    )
    parser.add_argument(
        "--model-probe",
        action="store_true",
        help="probe the provider directly; diagnostic only, never a protected release gate",
    )
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
    if not args.real and (args.runtime or args.model_probe):
        parser.error("--runtime/--model-probe 只能与 --real 一起使用")
    if args.real and args.runtime == args.model_probe:
        parser.error("真实评测必须且只能指定 --runtime 或 --model-probe")
    if args.require_real and not args.runtime:
        parser.error("受保护真实评测必须使用 --runtime；--model-probe 仅供诊断")
    if (args.require_real or args.allow_skip) and not args.real:
        parser.error("--require-real/--allow-skip 只能与 --real 一起使用")
    if args.require_real and args.allow_skip:
        parser.error("--require-real 与 --allow-skip 不能同时使用")
    if not 0 <= args.temperature <= 2:
        parser.error("--temperature 必须在 0 到 2 之间")
    try:
        prompt_version = validate_prompt_version(args.prompt_version)
    except EvalCaseError as exc:
        parser.error(str(exc))
    metadata = build_experiment_metadata(
        model_identifier=args.model.strip() or None,
        prompt_version=prompt_version,
        temperature=args.temperature,
    )
    if args.model.strip():
        metadata["model_override"] = args.model.strip()
    if args.runtime and args.model.strip():
        parser.error("--runtime 使用 settings 中的受保护模型配置，不接受 --model 覆盖")
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
        eval_cases = cases + bad_case_cases
        if args.runtime:
            observations, case_reports, collection_errors = collect_runtime_observations(
                eval_cases,
                metadata,
                require_remote_attestation=args.require_real,
            )
        else:
            observations, case_reports, collection_errors = collect_real_observations(
                eval_cases, metadata,
            )
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
