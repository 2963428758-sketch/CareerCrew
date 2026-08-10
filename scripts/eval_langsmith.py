"""LangSmith 评估闭环（AGENT_LANGSMITH_SPEC B5）。

把 ``CompositeEvaluator``（resume_match / interview_quality）包装为评估脚本：
注册 dataset、跑用例、以 feedback 回传评分到 LangSmith。

用法（需 .env 提供 LANGSMITH_API_KEY）：
    conda run -n careercrew python scripts/eval_langsmith.py
    conda run -n careercrew python scripts/eval_langsmith.py --business --thread-id m1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _bootstrap() -> None:
    sys.path.insert(0, str(PROJECT_ROOT))


def _current_run_id() -> str | None:
    from langsmith import get_current_run_tree

    tree = get_current_run_tree()
    return str(tree.id) if tree is not None else None


def _ensure_dataset(client, cases: list[dict]):
    name = "careercrew-eval"
    try:
        if client.has_dataset(dataset_name=name):
            return client.read_dataset(dataset_name=name)
        return client.create_dataset(
            dataset_name=name,
            description="CareerCrew 答案级评估（resume_match / interview_quality）",
        )
    except Exception:
        return client.read_dataset(dataset_name=name)


def _evaluate_resume(case: dict):
    from careercrew_core.evaluation.answer_eval import CompositeEvaluator

    ev = CompositeEvaluator(llm=None)
    r = ev.evaluate_resume(case["resume_text"], case["jd_text"])
    return "resume_match", r["score"], r.get("feedback") or f"max={r['max']}"


def _evaluate_interview(case: dict, llm):
    from careercrew_core.evaluation.answer_eval import CompositeEvaluator

    ev = CompositeEvaluator(llm=llm)
    r = ev.evaluate_interview(case["question"], case["answer"])
    return "interview_quality", r["score"], r.get("feedback") or f"max={r['max']}"


def _run_cases(client, settings, cases: list[dict]) -> int:
    from careercrew_ai.llm import create_llm
    from careercrew_core.tracing.langsmith import traced_call

    ds = _ensure_dataset(client, cases)
    print(f"[eval] dataset: {ds.name} ({getattr(ds, 'id', '?')})")
    if cases:
        try:
            client.create_examples(dataset_id=ds.id, examples=cases)
        except Exception as e:  # noqa: BLE001 - 已存在/重复时忽略
            print(f"[eval] create_examples 跳过: {e}")

    llm = create_llm(settings, max_tokens=512)
    for case in cases:
        ctype = case.get("case_type")

        def _run():
            if ctype == "resume_match":
                key, score, comment = _evaluate_resume(case)
            elif ctype == "interview_qa":
                key, score, comment = _evaluate_interview(case, llm)
            else:
                raise ValueError(f"未知 case_type: {ctype}")
            return key, score, comment, _current_run_id()

        key, score, comment, run_id = traced_call(
            _run,
            name="careercrew.eval",
            run_type="chain",
            run_metadata={"endpoint": "eval", "case_id": case.get("id", "")},
        )
        client.create_feedback(run_id=run_id, key=key, score=score, comment=comment)
        print(f"[eval] {case.get('id', ctype)} -> {key}={score}（run {run_id}）")
    return 0


def _run_business(client, args) -> int:
    from careercrew_core.evaluation.business_eval import BusinessEvaluator
    from careercrew_core.memory.episodic import EpisodicMemory
    from careercrew_core.tracing.langsmith import list_runs

    ep = EpisodicMemory(args.transcript)
    stats = BusinessEvaluator(ep).stats()
    print(f"[business] {json.dumps(stats, ensure_ascii=False)}")
    runs = list_runs(limit=50, thread_id=args.thread_id, project=args.project)
    if not runs:
        print(f"[business] 未找到 thread_id={args.thread_id} 的 run，仅打印统计")
        return 0
    latest = runs[0]
    client.create_feedback(
        run_id=latest["run_id"], key="business_funnel", value=stats,
        comment="求职漏斗统计（applications/interviews/offers）",
    )
    print(f"[business] feedback 已挂到 run {latest['run_id']}")
    return 0


def main() -> int:
    _bootstrap()
    ap = argparse.ArgumentParser(description="CareerCrew LangSmith 评估")
    ap.add_argument("--dataset", default=str(PROJECT_ROOT / "data" / "eval" / "cases.jsonl"))
    ap.add_argument("--project", default="careercrew")
    ap.add_argument("--business", action="store_true", help="只跑业务漏斗统计并挂 feedback")
    ap.add_argument("--transcript", default=str(PROJECT_ROOT / "data" / "transcripts" / "u_001" / "m1.jsonl"))
    ap.add_argument("--thread-id", default="m1")
    args = ap.parse_args()

    from careercrew_core.state.settings import load_settings
    from careercrew_core.tracing.langsmith import configure_langsmith

    settings = load_settings()
    configure_langsmith(settings)

    from langsmith.run_trees import get_cached_client

    client = get_cached_client()
    if args.business:
        return _run_business(client, args)

    cases = [
        json.loads(line)
        for line in Path(args.dataset).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return _run_cases(client, settings, cases)


if __name__ == "__main__":
    sys.exit(main())
