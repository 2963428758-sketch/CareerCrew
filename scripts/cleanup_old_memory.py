"""旧记忆数据清理脚本（记忆重构一次性迁移）。

删除对象（只删这些，绝不碰知识库/上传文件）：
1. data/transcripts/          —— 旧 JSONL 情景记忆
2. data/user_model.json       —— 旧单文件用户画像
3. data/db/checkpointer.db    —— 旧 SQLite LangGraph checkpointer（含 -wal/-shm）
4. Qdrant 旧 collection `careercrew_episodic`（若存在；当前配置指向的
   `careercrew_episodic_v2` 与知识库 collection 一律不动）

安全：所有路径解析后必须落在 <项目根>/data 内且文件名精确匹配才删除；
Qdrant 删除仅按配置里的"旧名"硬编码匹配，绝不用用户输入。

用法：conda run -n careercrew python scripts/cleanup_old_memory.py [--dry-run]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

# 精确目标（相对 data/ 的路径；仅这些会被删除）
_FILES = [
    Path("user_model.json"),
    Path("db/checkpointer.db"),
    Path("db/checkpointer.db-wal"),
    Path("db/checkpointer.db-shm"),
]
_DIRS = [Path("transcripts")]

_OLD_EPISODIC_COLLECTION = "careercrew_episodic"


def _safe_path(rel: Path) -> Path | None:
    """解析相对路径并校验落在 data/ 内；越界返回 None。"""
    resolved = (DATA_DIR / rel).resolve()
    try:
        resolved.relative_to(DATA_DIR.resolve())
    except ValueError:
        return None
    return resolved


def cleanup(dry_run: bool = True) -> list[str]:
    removed: list[str] = []
    for rel in _FILES:
        p = _safe_path(rel)
        if p is None:
            removed.append(f"SKIP(越界): {rel}")
            continue
        if p.exists():
            if dry_run:
                removed.append(f"[dry-run] 删除文件: {p}")
            else:
                p.unlink()
                removed.append(f"已删除文件: {p}")
    for rel in _DIRS:
        p = _safe_path(rel)
        if p is None:
            removed.append(f"SKIP(越界): {rel}")
            continue
        if p.exists() and p.is_dir():
            if dry_run:
                removed.append(f"[dry-run] 删除目录: {p}")
            else:
                shutil.rmtree(p)
                removed.append(f"已删除目录: {p}")
    removed.extend(_cleanup_qdrant(dry_run))
    return removed


def _cleanup_qdrant(dry_run: bool) -> list[str]:
    """删除 Qdrant 旧 episodic collection（best-effort：Qdrant 不可用则跳过）。"""
    out: list[str] = []
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from careercrew_core.state.settings import load_settings

        settings = load_settings()
        cfg = settings.vector_store
        if cfg.backend == "fake":
            return ["SKIP: vector_store.backend=fake，无真实 Qdrant"]
        from qdrant_client import QdrantClient

        client = QdrantClient(url=cfg.url or "http://localhost:6333", api_key=cfg.api_key or None)
        if client.collection_exists(_OLD_EPISODIC_COLLECTION):
            if dry_run:
                out.append(f"[dry-run] 删除 Qdrant collection: {_OLD_EPISODIC_COLLECTION}")
            else:
                client.delete_collection(_OLD_EPISODIC_COLLECTION)
                out.append(f"已删除 Qdrant collection: {_OLD_EPISODIC_COLLECTION}")
        else:
            out.append("Qdrant 旧 episodic collection 不存在，跳过")
    except Exception as e:  # noqa: BLE001 - 清理脚本 best-effort
        out.append(f"SKIP Qdrant: {e}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="清理旧记忆数据")
    parser.add_argument("--dry-run", action="store_true", help="只列出将删除的目标，不实际删除")
    args = parser.parse_args()

    print(f"项目根: {PROJECT_ROOT}")
    print(f"数据目录: {DATA_DIR.resolve()}")
    print("目标：")
    for rel in _FILES:
        print(f"  file {rel}")
    for rel in _DIRS:
        print(f"  dir  {rel}")
    print(f"  qdrant collection {_OLD_EPISODIC_COLLECTION}")
    print("注意：知识库 collection / data/uploads / data/knowledge 不受影响。\n")

    if not args.dry_run and not _confirm():
        print("已取消")
        return 1
    for line in cleanup(dry_run=args.dry_run):
        print(" -", line)
    print("\n完成。")
    return 0


def _confirm() -> bool:
    ans = input("确认删除以上旧记忆数据？输入 yes 继续: ").strip().lower()
    return ans == "yes"


if __name__ == "__main__":
    raise SystemExit(main())
