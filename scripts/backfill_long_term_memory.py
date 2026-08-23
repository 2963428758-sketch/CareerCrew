"""将兼容记忆表安全回填到 memory_records。

默认 dry-run：只输出扫描和候选数量。必须显式传 ``--apply`` 才会写新表；普通
user_message / agent_response 永远不会成为回填候选。
"""
from __future__ import annotations

import argparse
import json
import sys

from careercrew_core.state.settings import load_settings
from careercrew_core.memory import create_memory_db
from careercrew_core.memory.records import LongTermMemoryRepository, build_legacy_backfill


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", action="append", required=True, help="可重复指定需要回填的用户")
    parser.add_argument("--apply", action="store_true", help="确认写入 memory_records（默认仅 dry-run）")
    args = parser.parse_args(argv)

    db = create_memory_db(load_settings())
    report = build_legacy_backfill(db, args.user_id)
    output: dict[str, object] = {"mode": "apply" if args.apply else "dry-run", **report.summary()}
    if args.apply:
        output["result"] = LongTermMemoryRepository(db).apply_backfill(report)
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
