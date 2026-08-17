"""Export approved eval cases into a versioned JSONL dataset (§30).

Usage:
    python scripts/export_eval_dataset.py --version v1 [--dsn $POSTGRES_DSN]

Writes ``evals/careercrew/<version>/cases.jsonl``; the server itself never
writes git-tracked files, so CI/dev run this script instead.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from careercrew_core.conversation.db import PostgresConversationDb  # noqa: E402
from careercrew_core.conversation.store import ConversationStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Export approved eval cases to versioned JSONL")
    parser.add_argument("--version", default="v1", help="dataset version directory (default v1)")
    parser.add_argument("--dsn", default=os.environ.get("POSTGRES_DSN", ""), help="Postgres DSN")
    parser.add_argument("--out", default="", help="output file override (default evals/careercrew/<version>/cases.jsonl)")
    args = parser.parse_args()
    if not args.dsn:
        parser.error("需要 --dsn 或环境变量 POSTGRES_DSN")

    store = ConversationStore(PostgresConversationDb(args.dsn))
    rows = store.export_eval_cases()
    if args.out:
        target = Path(args.out)
    else:
        target = Path("evals") / "careercrew" / args.version / "cases.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    print(f"已导出 {len(rows)} 个 approved eval case -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())