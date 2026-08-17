"""会话附件 TTL 清理脚本（T3.1 §14.5）。

删除 ``expires_at < now`` 且 status 非 ``saved_to_knowledge`` 的附件：先物理删文件，
再删 DB 行。保存到知识库（saved_to_knowledge / expires_at=NULL）的附件永不清理。

定时说明（部署者必读）：
- 建议每日定时运行一次（cron / 任务调度器），对齐 §14.5「每日定时 cleanup」。
  Linux cron 示例：
      `0 3 * * *  cd /path/to/CareerCrew && uv run python scripts/cleanup_chat_attachments.py`
  Windows 任务计划程序：每天 03:00 运行 `uv run python scripts/cleanup_chat_attachments.py`。

用法：
    uv run python scripts/cleanup_chat_attachments.py [--dry-run]

安全：磁盘路径一律由 DB 里的 storage_key（相对 attachments 根）+ resolve_under
校验，绝不接受用户输入构造路径。
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def cleanup_expired(store, attachments_root: Path, now: datetime | None = None,
                    dry_run: bool = True) -> list[str]:
    """清理过期附件：返回逐条结果字符串；dry_run 只列出不删除。"""
    from careercrew_api.storage import resolve_under

    results: list[str] = []
    expired = store.expired_attachments(now=now or datetime.now(timezone.utc))
    for row in expired:
        # storage_key 相对 attachments 根；resolve_under 防目录穿越。
        try:
            disk_path = resolve_under(
                attachments_root, *(row["storage_key"].split("/"))
            )
        except ValueError as e:
            results.append(f"SKIP(越界): {row['id']} ({e})")
            continue
        if dry_run:
            results.append(f"[dry-run] 删除附件: {row['id']} ({row['original_filename']})")
            continue
        disk_path.unlink(missing_ok=True)
        store.delete(row["user_id"], row["id"])
        results.append(f"已删除附件: {row['id']} ({row['original_filename']})")
    return results


def _load_store():
    """加载生产配置的 AttachmentStore + attachments 根目录。"""
    import sys

    sys.path.insert(0, str(PROJECT_ROOT))
    from careercrew_api import storage
    from careercrew_core.conversation.attachments import (
        AttachmentStore,
        create_attachment_db,
    )
    from careercrew_core.state.settings import load_settings

    store = AttachmentStore(create_attachment_db(load_settings()))
    return store, storage.L.attachments


def main() -> int:
    parser = argparse.ArgumentParser(description="清理过期会话附件（TTL 7 天）")
    parser.add_argument("--dry-run", action="store_true", help="只列出将删除的附件，不实际删除")
    args = parser.parse_args()

    store, attachments_root = _load_store()
    results = cleanup_expired(store, attachments_root, dry_run=args.dry_run)
    for line in results:
        print(" -", line)
    print(f"\n完成（{len(results)} 条过期附件{'，dry-run 未实际删除' if args.dry_run else ''}）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
