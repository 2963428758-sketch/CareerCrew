"""LangSmith 慢 trace 诊断（REST 直查；SDK 在部分网络下会挂起）。

用法：
    python scripts/diag_langsmith_slow.py                # 最近 root runs + 自动深挖最慢者
    python scripts/diag_langsmith_slow.py --list-only    # 只列不挖
依赖 .env 的 LANGSMITH_API_KEY；project 名取 config/settings.yaml 的 langsmith.project。
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

KEY = os.environ["LANGSMITH_API_KEY"]
PROJECT = "careercrew"
API = "https://api.smith.langchain.com/api/v1"


def _post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"x-api-key": KEY, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def runs_of(resp):
    return resp.get("runs", []) if isinstance(resp, dict) else resp


def dur(r: dict) -> float | None:
    s, e = r.get("start_time"), r.get("end_time")
    if not (s and e):
        return None
    p = lambda t: datetime.fromisoformat(t.replace("Z", "+00:00"))  # noqa: E731
    return (p(e) - p(s)).total_seconds()


def resolve_session() -> str:
    req = urllib.request.Request(
        f"{API}/sessions/?name={PROJECT}", headers={"x-api-key": KEY}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        sessions = json.load(resp)
    sessions = sessions.get("sessions") if isinstance(sessions, dict) else sessions
    if not sessions:
        raise SystemExit(f"找不到项目 {PROJECT}")
    return sessions[0]["id"]


def dump_children(session_id: str, target_id: str) -> None:
    children = runs_of(_post("/runs/query", {"trace": target_id, "limit": 100}))
    children.sort(key=lambda r: r.get("start_time") or "")
    by_parent: dict[str | None, list[dict]] = {}
    for c in children:
        by_parent.setdefault(c.get("parent_run_id"), []).append(c)

    def walk(parent_id: str | None, depth: int) -> None:
        for c in by_parent.get(parent_id, []):
            d = dur(c) or 0.0
            extra = ""
            if c["run_type"] == "llm":
                em = (c.get("extra") or {}).get("metadata", {})
                model = em.get("ls_model_name", "")
                extra = (
                    f"model={model} tok(in/out)="
                    f"{c.get('prompt_tokens')}/{c.get('completion_tokens')}"
                )
            err = " ERROR!" if c.get("error") else ""
            print("  " * depth + f"- {c['name']} [{c['run_type']}] {d:.1f}s {extra}{err}")
            walk(c["id"], depth + 1)

    walk(None, 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-only", action="store_true")
    args = ap.parse_args()

    session_id = resolve_session()
    runs = runs_of(_post("/runs/query", {"session": [session_id], "is_root": True, "limit": 10}))
    print(f"{'#':>2} {'耗时':>8}  开始(UTC)            名称")
    for i, r in enumerate(runs):
        print(f"{i:>2} {dur(r):>7.1f}s  {r['start_time'][:19]}  {r['name']}")

    if args.list_only or not runs:
        return
    target = max(runs, key=lambda r: dur(r) or 0)
    print(f"\n===== 深挖最慢: {target['name']} {dur(target):.1f}s =====")
    dump_children(session_id, target["id"])


if __name__ == "__main__":
    main()
