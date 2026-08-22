"""会话附件 TTL 清理 CLI（T3.1 §14.5）。

核心实现已抽到 careercrew_api.maintenance（lifespan 后台循环共用同一份逻辑，
生产部署无需再配 cron——应用启动即自动每日清理）。本脚本保留用于：
- 手动触发 / dry-run 预览
- 未接入后台循环的旧版本部署

用法：
    uv run python scripts/cleanup_chat_attachments.py [--dry-run]
"""
from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description="清理过期会话附件（TTL 7 天）")
    parser.add_argument("--dry-run", action="store_true", help="只列出将删除的附件，不实际删除")
    args = parser.parse_args()

    from careercrew_api.maintenance import run_attachment_cleanup_once

    results = run_attachment_cleanup_once(dry_run=args.dry_run)
    for line in results:
        print(" -", line)
    print(f"\n完成（{len(results)} 条过期附件{'，dry-run 未实际删除' if args.dry_run else ''}）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
