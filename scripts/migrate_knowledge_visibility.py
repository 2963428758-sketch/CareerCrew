"""知识库集合 payload 迁移：user_id → owner_user_id + visibility=private。

物理 ID 不变（_to_qid 只依赖 owner 的值，不依赖键名）。默认 dry-run。
只处理知识库集合；情景记忆集合（careercrew_episodic_v2）继续用 user_id，不受影响。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def migrate_collection(client, collection: str, default_owner: str, *, apply: bool):
    """返回 (changed, skipped, conflicts)。apply 时写 owner_user_id/visibility 并删除 user_id 键。"""
    changed = skipped = conflicts = 0
    offset = None
    while True:
        points, offset = client.scroll(
            collection, limit=256, offset=offset, with_payload=True, with_vectors=False
        )
        for point in points:
            payload = dict(point.payload or {})
            owner = str(payload.get("user_id") or payload.get("owner_user_id") or default_owner)
            if payload.get("owner_user_id") and payload.get("visibility"):
                skipped += 1
                continue
            existing_owner = payload.get("owner_user_id")
            if existing_owner and existing_owner != owner:
                conflicts += 1
                continue
            changed += 1
            if apply:
                client.set_payload(
                    collection,
                    payload={"owner_user_id": owner, "visibility": "private", "user_id": None},
                    points=[point.id],
                )
        if offset is None:
            break
    return changed, skipped, conflicts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", default="", help="默认读 settings 的 knowledge 集合")
    parser.add_argument("--default-owner", default="u_001")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(PROJECT_ROOT))
    from qdrant_client import QdrantClient

    from careercrew_core.state.settings import load_settings

    settings = load_settings()
    cfg = settings.vector_store
    collection = args.collection or cfg.collections["knowledge"]
    if (cfg.url or "").strip() == ":memory:":
        raise SystemExit("不能在 :memory: 后端上执行真实迁移")
    client = QdrantClient(url=cfg.url, api_key=cfg.api_key or None)
    if not client.collection_exists(collection):
        raise SystemExit(f"集合不存在：{collection}")
    changed, skipped, conflicts = migrate_collection(
        client, collection, args.default_owner, apply=args.apply
    )
    print(f"mode={'APPLY' if args.apply else 'DRY-RUN'} collection={collection} "
          f"changed={changed} skipped={skipped} conflicts={conflicts}")
    return 1 if conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
