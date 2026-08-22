"""后台维护任务：附件 TTL 清理等（lifespan 守护线程与 CLI 脚本共用实现）。"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# 附件 TTL 默认 7 天，清理周期 24h 足够；如需调整改此处（YAGNI：暂不进 yaml）
CLEANUP_INTERVAL_SECONDS = 24 * 3600


def cleanup_expired_attachments(
    store, attachments_root: Path, now: datetime | None = None, dry_run: bool = True
) -> list[str]:
    """删除 ``expires_at < now`` 且未保存到知识库的附件：先删文件再删 DB 行。

    dry_run=True 只列出将删除项。返回逐条结果字符串。
    磁盘路径一律由 DB 的 storage_key（相对 attachments 根）+ resolve_under 校验，
    绝不接受用户输入构造路径。
    """
    from careercrew_api.storage import resolve_under

    results: list[str] = []
    expired = store.expired_attachments(now=now or datetime.now(UTC))
    for row in expired:
        try:
            disk_path = resolve_under(attachments_root, *(row["storage_key"].split("/")))
        except ValueError as e:
            results.append(f"SKIP(越界): {row['id']} ({e})")
            continue
        label = f"{row['id']} ({row['original_filename']})"
        if dry_run:
            results.append(f"[dry-run] 删除附件: {label}")
            continue
        disk_path.unlink(missing_ok=True)
        store.delete(row["user_id"], row["id"])
        results.append(f"已删除附件: {label}")
    return results


def run_attachment_cleanup_once(dry_run: bool = False) -> list[str]:
    """以生产配置构造 AttachmentStore 执行一轮清理（供后台循环 / CLI）。"""
    from careercrew_api import storage
    from careercrew_core.conversation.attachments import (
        AttachmentStore,
        create_attachment_db,
    )
    from careercrew_core.state.settings import load_settings

    store = AttachmentStore(create_attachment_db(load_settings()))
    return cleanup_expired_attachments(store, storage.L.attachments, dry_run=dry_run)
