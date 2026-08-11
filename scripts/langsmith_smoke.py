"""LangSmith 冒烟：连接 + 合成 run 回读断言脱敏生效（不启动重栈）。

用法：conda run -n careercrew python scripts/langsmith_smoke.py
退出码 0=通过；1=失败（连接失败 / 脱敏未生效）。
"""
from __future__ import annotations

import json
import sys
import time
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    sys.path.insert(0, str(PROJECT_ROOT))
    ap = argparse.ArgumentParser(description="LangSmith 冒烟 / 只读查看")
    ap.add_argument(
        "--list", action="store_true",
        help="只读列出 careercrew 项目最近根 run（不创建任何 run）",
    )
    args = ap.parse_args()

    from careercrew_core.state.settings import load_settings
    from careercrew_core.tracing.langsmith import configure_langsmith, traced_call

    settings = load_settings()
    configure_langsmith(settings)

    if args.list:
        from careercrew_core.tracing.langsmith import list_runs

        runs = list_runs(limit=20)
        if not runs:
            print("[list] 无 run（先跑一次对话再来看）")
            return 0
        for r in runs:
            print(
                f"  {r['start_time']} | {r['name']} | {r['status']} "
                f"| tokens={r['total_tokens']} | {r['metadata']}"
            )
        print(f"[list] 共 {len(runs)} 条根 run")
        return 0

    long_text = "敏感内容" * 1000  # 4000 字符，远超 max_chars=2000
    phone = "13800138000"
    email = "zhangsan@example.com"
    salary = "期望 30-40K，最低 25万"

    def _create(phone=None, email=None, salary=None, resume=None):
        from langsmith import get_current_run_tree

        tree = get_current_run_tree()
        return str(tree.id) if tree is not None else None

    run_id = traced_call(
        _create,
        name="careercrew.smoke",
        run_type="chain",
        run_metadata={"endpoint": "smoke"},
        phone=phone,
        email=email,
        salary=salary,
        resume=long_text,
    )
    if not run_id:
        print("[smoke] FAIL: 未创建 run（tracing 未启用？）")
        return 1

    from langsmith.run_trees import get_cached_client

    client = get_cached_client()
    client.flush()  # 异步批处理可能未落库，先 flush
    run = None
    for _ in range(10):
        try:
            run = client.read_run(run_id)
            break
        except Exception:  # noqa: BLE001 - 未落库重试
            time.sleep(1)
    if run is None:
        print(f"[smoke] FAIL: run 未落库（run_id={run_id}）")
        return 1
    masked = json.dumps(getattr(run, "inputs", None) or {}, ensure_ascii=False)
    checks = {
        "手机号已打码": phone not in masked and "手机号已隐藏" in masked,
        "邮箱已打码": email not in masked and "邮箱已隐藏" in masked,
        "薪资已打码": "30-40K" not in masked and "25万" not in masked,
        "长文本已截断": "…[已截断]" in masked and len(long_text) > 2000,
    }
    ok = True
    for name, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print(f"[smoke] run_id={run_id}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
