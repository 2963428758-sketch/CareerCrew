"""Agent/RAG 离线评估 runner + 版本化 baseline 非回归门禁。

用法：
    python scripts/eval_runner.py --offline                      # fixtures 计算指标并打印
    python scripts/eval_runner.py --offline --report out.json    # 指标写 JSON
    python scripts/eval_runner.py --offline --update-baseline    # 更新 data/eval/baseline.json
    python scripts/eval_runner.py --offline --compare data/eval/baseline.json --fail-on-regression
    python scripts/eval_runner.py --real                         # 真实模型/服务（nightly/manual）

离线模式：观测值来自 data/eval/fixtures/*.json（预录制检索结果/路由/回答/工具调用）。
真实模式：collect_real(case) 返回同结构观测（依赖真实模型与服务；缺 key 时提示退出 0）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EVAL_DIR = Path(__file__).resolve().parents[1] / "data" / "eval"
CASES_PATH = EVAL_DIR / "cases.jsonl"
BASELINE_PATH = EVAL_DIR / "baseline.json"
FIXTURES_GLOB = "fixtures/*.json"
REGRESSION_TOLERANCE = 0.01


# ── 指标（纯函数，可单测）──

def hit_at_k(predicted: list[list[str]], expected: list[list[str]], k: int = 5) -> float:
    """Hit@K：期望 doc 是否出现在每例前 k 个结果中（0/1 均值）。"""
    if not expected:
        return 1.0
    hits = [
        1.0 if any(d in pred[:k] for d in exp) else 0.0
        for pred, exp in zip(predicted, expected, strict=False)
    ]
    return sum(hits) / len(hits)


def mrr(predicted: list[list[str]], expected: list[list[str]]) -> float:
    """MRR：期望 doc 的倒数排名均值（未命中计 0）。"""
    if not expected:
        return 1.0
    scores = []
    for pred, exp in zip(predicted, expected, strict=False):
        best = 0.0
        for d in exp:
            try:
                rank = pred.index(d) + 1
                best = max(best, 1.0 / rank)
            except ValueError:
                continue
        scores.append(best)
    return sum(scores) / len(scores)


def citation_coverage(answer: str, must_include: list[str]) -> float:
    """引用覆盖：答案中包含的必须引用点比例。"""
    if not must_include:
        return 1.0
    return sum(1.0 for p in must_include if p in answer) / len(must_include)


def route_accuracy(predicted: list[str], expected: list[str]) -> float:
    """路由准确率：逐例是否一致。"""
    if not expected:
        return 1.0
    return sum(1.0 for p, e in zip(predicted, expected, strict=False) if p == e) / len(expected)


def tool_success(tool_lists: list[list[str]], expected: list[list[str]]) -> float:
    """工具成功率：期望工具是否全部出现在记录调用中。"""
    if not expected:
        return 1.0
    ok = [
        1.0 if all(t in tools for t in exp) else 0.0
        for tools, exp in zip(tool_lists, expected, strict=False)
    ]
    return sum(ok) / len(ok)


def retention(answer: str, points: list[str]) -> float:
    """记忆保留：压缩后答案中仍保留的要点比例。"""
    if not points:
        return 1.0
    return sum(1.0 for p in points if p in answer) / len(points)


# ── 观测收集 ──

def load_cases(path: Path = CASES_PATH) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_offline_observations(eval_dir: Path = EVAL_DIR) -> dict[str, dict]:
    obs: dict[str, dict] = {}
    fixtures_dir = eval_dir / "fixtures"
    if not fixtures_dir.exists():
        return obs
    for f in sorted(fixtures_dir.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        obs.update(data)
    return obs


def collect_real(case: dict) -> dict:
    """真实模型/服务观测（nightly/manual 使用）。依赖真实 embedding/LLM/Qdrant。

    当前框架占位：真实评估需本地 conda env 与 API key，缺 key/服务时给出提示并退出。
    """
    raise RuntimeError(
        "真实模型评估依赖本地重组件（BGE-M3/Qdrant/硅基流动 API）。"
        "请在本地 conda env 实现 collect_real 或在 CI secrets 就绪后启用。"
    )


# ── 指标汇总 ──

def compute_metrics(cases: list[dict], obs: dict[str, dict]) -> dict:
    by_kind: dict[str, list[dict]] = {}
    for c in cases:
        by_kind.setdefault(c["kind"], []).append(c)

    metrics: dict[str, float] = {}

    def _obs(c: dict) -> dict:
        o = obs.get(c["id"])
        if o is None:
            raise KeyError(f"case {c['id']} 缺少观测值（fixtures 或 --real）")
        return o

    route_cases = by_kind.get("route", [])
    if route_cases:
        metrics["route_accuracy"] = route_accuracy(
            [_obs(c).get("route", "") for c in route_cases],
            [c["expected"]["route"] for c in route_cases],
        )

    ret_cases = by_kind.get("retrieval", [])
    if ret_cases:
        k = max((c["expected"].get("k", 5) for c in ret_cases), default=5)
        metrics["hit_at_5"] = hit_at_k(
            [_obs(c).get("retrieved", []) for c in ret_cases],
            [c["expected"]["doc_ids"] for c in ret_cases],
            k=k,
        )
        metrics["mrr"] = mrr(
            [_obs(c).get("retrieved", []) for c in ret_cases],
            [c["expected"]["doc_ids"] for c in ret_cases],
        )

    cit_cases = by_kind.get("citation", [])
    if cit_cases:
        metrics["citation_coverage"] = sum(
            citation_coverage(_obs(c).get("answer", ""), c["expected"]["must_include"])
            for c in cit_cases
        ) / len(cit_cases)

    tool_cases = by_kind.get("tool", [])
    if tool_cases:
        metrics["tool_success"] = tool_success(
            [_obs(c).get("tools", []) for c in tool_cases],
            [c["expected"]["tool_names"] for c in tool_cases],
        )

    mem_cases = by_kind.get("memory", [])
    if mem_cases:
        metrics["memory_hit"] = sum(
            1.0 if bool(_obs(c).get("memory_hit")) == bool(c["expected"].get("memory_hit"))
            else 0.0
            for c in mem_cases
        ) / len(mem_cases)
        metrics["retention"] = sum(
            retention(_obs(c).get("answer", ""), c["expected"].get("retention_ref", []))
            for c in mem_cases
        ) / len(mem_cases)

    consult_cases = by_kind.get("consult", [])
    if consult_cases:
        metrics["consult_agent_coverage"] = sum(
            1.0 if all(a in _obs(c).get("agents", []) for a in c["expected"]["expected_agents"])
            else 0.0
            for c in consult_cases
        ) / len(consult_cases)
        metrics["consult_avg_latency_s"] = sum(
            float(_obs(c).get("latency_s", 0.0)) for c in consult_cases
        ) / len(consult_cases)
        metrics["consult_avg_tokens"] = sum(
            float(_obs(c).get("tokens", 0.0)) for c in consult_cases
        ) / len(consult_cases)

    return metrics


# ── 基线门禁 ──

def compare_baseline(metrics: dict, baseline: dict) -> list[str]:
    regressions = []
    for key, base in baseline.items():
        if key not in metrics:
            regressions.append(f"{key}: 缺失（基线 {base}）")
            continue
        if metrics[key] < base - REGRESSION_TOLERANCE:
            regressions.append(f"{key}: {metrics[key]} < 基线 {base}")
    return regressions


# §32 发布门禁阈值：率指标允许相对下降，延迟/成本允许相对上升。
BAD_CASE_DROP_LIMIT = 0.02
RELEASE_GATE = {
    "bad_case_pass_rate": ("drop", BAD_CASE_DROP_LIMIT),
    "route_accuracy": ("drop", 0.01),
    "citation_coverage": ("drop", 0.03),
    "tool_success": ("drop", 0.01),
    "consult_avg_latency_s": ("rise", 0.20),
    "consult_avg_tokens": ("rise", 0.25),
}


def case_passes(obs: dict, rubric: dict) -> bool:
    """Rubric 启发式判定：must_include 全含、must_not_contain 全不含。"""
    answer = obs.get("answer", "") or ""
    for term in rubric.get("must_include", []) or []:
        if term not in answer:
            return False
    for term in rubric.get("must_not_contain", []) or []:
        if term in answer:
            return False
    return True


def bad_case_pass_rate(cases: list[dict], obs: dict[str, dict]) -> float:
    if not cases:
        return 1.0
    return sum(case_passes(obs.get(c["id"], {}), c.get("rubric") or {}) for c in cases) / len(cases)


def gate_regressions(metrics: dict, baseline: dict) -> list[str]:
    """按 §32 相对阈值检查发布门禁，返回未通过项。"""
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent/RAG 评估 runner")
    parser.add_argument("--offline", action="store_true", help="用 fixtures 观测计算指标")
    parser.add_argument("--real", action="store_true", help="真实模型/服务观测（nightly/manual）")
    parser.add_argument("--bad-cases", default="", help="bad-case 数据集 JSONL 路径（导出脚本产物，§29/§30）")
    parser.add_argument("--update-baseline", action="store_true", help="把本次指标写入 baseline.json")
    parser.add_argument("--compare", default="", help="对比基线文件路径")
    parser.add_argument("--fail-on-regression", action="store_true", help="任一指标低于基线时非零退出")
    parser.add_argument("--report", default="", help="指标 JSON 输出路径")
    args = parser.parse_args()

    cases = load_cases()
    bad_case_cases = load_cases(Path(args.bad_cases)) if args.bad_cases else []
    if not cases and not bad_case_cases:
        print("data/eval/cases.jsonl 为空或不存在")
        return 2

    if args.offline:
        obs = load_offline_observations()
    elif args.real:
        try:
            obs = {c["id"]: collect_real(c) for c in cases + bad_case_cases}
        except RuntimeError as e:
            print(f"[real eval skipped] {e}")
            return 0
    else:
        parser.error("必须指定 --offline 或 --real")

    metrics = compute_metrics(cases, obs)
    if bad_case_cases:
        metrics["bad_case_pass_rate"] = bad_case_pass_rate(bad_case_cases, obs)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))

    if args.update_baseline:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"baseline 已更新: {BASELINE_PATH}")

    if args.report:
        Path(args.report).write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.compare:
        baseline = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        regressions = compare_baseline(metrics, baseline)
        if regressions:
            print("回归:")
            for r in regressions:
                print(f"  - {r}")
            if args.fail_on_regression:
                return 1
        else:
            print("无回归（全部指标不低于基线）")
        gate = gate_regressions(metrics, baseline)
        if gate:
            print("发布门禁未通过（§32）:")
            for r in gate:
                print(f"  - {r}")
            if args.fail_on_regression:
                return 1
        else:
            print("发布门禁通过（§32 阈值内）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
