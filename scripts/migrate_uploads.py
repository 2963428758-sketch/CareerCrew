"""历史 data/uploads 显式迁移命令（默认 dry-run）。

用法：
    python scripts/migrate_uploads.py            # 只打印计划
    python scripts/migrate_uploads.py --apply    # 执行移动
    python scripts/migrate_uploads.py --owner u_001 --apply

幂等：目标已存在则跳过；文件名统一经 Path(...).name 归一，目标路径经
resolve_under 校验（目录穿越直接拒绝）。
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from careercrew_api.storage import L, resolve_under
from scripts.audit_uploads import audit


def plan_moves(rows: list[dict], lay: object = L) -> list[tuple[Path, Path]]:
    moves = []
    for r in rows:
        if r["kind"] not in ("resume", "knowledge"):
            continue
        src = Path(r["path"])
        target = resolve_under(
            lay.resumes_raw if r["kind"] == "resume" else lay.knowledge_raw,
            r["owner"],
            Path(r["suggested_target"]).name,
        )
        moves.append((src, target))
    return moves


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移历史 data/uploads 到 UUID 新布局")
    parser.add_argument("--apply", action="store_true", help="实际执行移动（默认 dry-run）")
    parser.add_argument("--owner", default="u_001", help="顶层散落文件归属（默认 u_001）")
    args = parser.parse_args()

    rows = audit()
    moved = skipped = 0
    for src, target in plan_moves(rows):
        if target.exists():
            print(f"[skip] {src} -> {target}（目标已存在）")
            skipped += 1
            continue
        print(f"{'[move]' if args.apply else '[plan]'} {src} -> {target}")
        if args.apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(target))
            moved += 1
    print(f"共 {len(rows)} 个文件：计划移动 {len(rows) - skipped}，已跳过 {skipped}"
          + (f"，已移动 {moved}" if args.apply else "（dry-run，未改动磁盘）"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
