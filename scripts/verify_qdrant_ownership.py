"""Qdrant owner 迁移校验 + snapshot + 迁移报告（Phase 0 / T0.2）。

方案 §5.1 迁移规则：无 owner 的历史私有数据 → owner_user_id = u_001。

与 scripts/migrate_knowledge_visibility.py 的分工：
- 知识库集合（careercrew_mm）以 owner_user_id 键为准；
- 情景记忆集合（careercrew_episodic_v2）以 user_id 键为准（既有设计，见
  migrate_knowledge_visibility.py docstring）；
- 本脚本额外提供：snapshot、unowned 计数、方案要求的 JSON 迁移报告、
  迁移后自动复跑 dry-run 校验（changed=0 / conflicts=0 / unowned=0）。

要点：
- 默认 dry-run（不写数据）；--apply 才回填 owner_user_id=u_001。
- unowned = 既无 owner_user_id 也无 user_id 的孤儿点。
- changed = 本次会写入 owner_user_id 的点数（仅孤儿点，apply 模式生效时计）。
- conflicts = owner_user_id 已存在但值与 default-owner 不一致的点数，绝不覆盖。
- apply 时先对每个集合 snapshot；snapshot 失败则中止（dry-run 仅告警继续）。
- 迁移后（--apply）自动复跑 dry-run，changed/conflicts/unowned 非 0 则 exit 1。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 回填 owner 的固定值（方案 §5.1 迁移规则）
ORPHAN_OWNER = "u_001"

# 集合名 -> 判定 owned 的主键（knowledge 用 owner_user_id，episodic 用 user_id）。
# 孤儿判定：两个键都不存在。回填统一写 owner_user_id。
COLLECTION_KEY_FIELD = {
    "careercrew_mm": "owner_user_id",
    "careercrew_episodic_v2": "user_id",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── 纯逻辑（可单测，与 I/O 解耦） ──


def _classify_point(payload: dict | None, key_field: str) -> str:
    """对单点分类：owned | orphan。key_field 指明该集合的主 ownership 键。

    考虑两个键：只要任一键存在即视为 owned（前一轮回填 owner_user_id 的 episodic
    点也算 owned）；两键皆无才视为 orphan。
    """
    p = payload or {}
    if p.get("owner_user_id") is not None or p.get("user_id") is not None:
        return "owned"
    return "orphan"


def scan_collection(client, collection: str, key_field: str) -> list[dict]:
    """扫描集合，返回每点的分类信息（不写数据）。"""
    result = []
    offset = None
    while True:
        points, offset = client.scroll(
            collection, limit=256, offset=offset, with_payload=True, with_vectors=False
        )
        for point in points:
            payload = dict(point.payload or {})
            kind = _classify_point(payload, key_field)
            result.append({"id": point.id, "payload": payload, "kind": kind})
        if offset is None:
            break
    return result


def verify_collection(client, collection: str, key_field: str, *,
                      apply: bool, default_owner: str) -> tuple[int, int, int, int, int]:
    """扫描并（apply 时）回填孤儿点。返回 (scanned, unowned, changed, skipped, conflicts)。"""
    scanned = unowned = changed = skipped = conflicts = 0
    for row in scan_collection(client, collection, key_field):
        scanned += 1
        payload = row["payload"]
        if row["kind"] == "owned":
            # owned 但 owner_user_id 存在且与默认不一时视为冲突（不覆盖）
            owner = payload.get("owner_user_id")
            if owner is not None and owner != default_owner and owner != ORPHAN_OWNER:
                conflicts += 1
            else:
                skipped += 1
            continue
        # orphan：两键皆无 → 回填 owner_user_id
        unowned += 1
        changed += 1
        if apply:
            client.set_payload(
                collection,
                payload={"owner_user_id": default_owner},
                points=[row["id"]],
            )
    return scanned, unowned, changed, skipped, conflicts


def snapshot_collection(client, collection: str) -> str | None:
    """对集合 POST snapshot 并返回名称；失败返回 None（不抛）。"""
    try:
        snapshot = client.create_snapshot(collection)
    except Exception:
        return None
    name = None
    if isinstance(snapshot, str):
        name = snapshot
    elif isinstance(snapshot, dict):
        result = snapshot.get("result") or snapshot
        name = result.get("name")
    # qdrant-client 某些版本直接返回含 name 的对象
    if not name:
        name = getattr(snapshot, "name", None)
    return name


# ── 报告构建 ──


def build_report(snapshot_ids: dict[str, str | None], per_collection: dict,
                 started_at: str, finished_at: str, mode: str) -> dict:
    """组装方案 §5.1 要求的迁移报告 JSON。"""
    scanned = sum(c["points"] for c in per_collection.values())
    updated = sum(c["changed"] for c in per_collection.values())
    conflicts = sum(c["conflicts"] for c in per_collection.values())
    unresolved = conflicts  # 冲突无法解决，二者语义一致时同值
    return {
        "snapshot_id": snapshot_ids,
        "scanned": scanned,
        "updated": updated,
        "conflicts": conflicts,
        "unresolved": unresolved,
        "started_at": started_at,
        "finished_at": finished_at,
        "mode": mode,
        "collections": per_collection,
    }


def write_report(report: dict, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


# ── 编排 ──


def run(client, collections: dict[str, str], *, apply: bool,
        default_owner: str) -> tuple[dict, list[str]]:
    """对多个集合执行校验/迁移编排，返回 (report, warnings)。

    collections: {collection_name: key_field}
    """
    started_at = _now_iso()
    snapshot_ids: dict[str, str | None] = {}
    per_collection: dict[str, dict] = {}
    warnings: list[str] = []

    for collection, key_field in collections.items():
        name = snapshot_collection(client, collection)
        snapshot_ids[collection] = name
        if name is None:
            msg = f"snapshot 失败：{collection}"
            if apply:
                raise RuntimeError(f"{msg}（apply 模式中止）")
            warnings.append(msg + "（dry-run 告警继续）")

        scanned, unowned, changed, skipped, conflicts = verify_collection(
            client, collection, key_field, apply=apply, default_owner=default_owner
        )
        per_collection[collection] = {
            "key_field": key_field,
            "points": scanned,
            "unowned": unowned,
            "changed": changed,
            "skipped": skipped,
            "conflicts": conflicts,
        }

    finished_at = _now_iso()
    report = build_report(snapshot_ids, per_collection, started_at, finished_at,
                          "APPLY" if apply else "DRY-RUN")
    return report, warnings


def build_client():
    sys.path.insert(0, str(PROJECT_ROOT))
    from qdrant_client import QdrantClient

    from careercrew_core.state.settings import load_settings

    settings = load_settings()
    cfg = settings.vector_store
    if (cfg.url or "").strip() == ":memory:":
        raise SystemExit("不能在 :memory: 后端上执行真实校验/迁移")
    return QdrantClient(url=cfg.url, api_key=cfg.api_key or None), cfg


def resolve_collections(client, cfg, selection: str | None) -> dict[str, str]:
    """返回要处理的 {collection_name: key_field}。默认（无 --collection）处理两者。"""
    known = {
        cfg.collections["knowledge"]: "owner_user_id",
        cfg.collections["episodic_memory"]: "user_id",
    }
    if selection:
        if selection not in known:
            raise SystemExit(f"未知集合：{selection}（已知：{sorted(known)}）")
        return {selection: known[selection]}
    # 只处理真实存在的集合
    return {c: k for c, k in known.items() if client.collection_exists(c)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", default="", help="仅处理指定集合（默认两个都处理）")
    parser.add_argument("--default-owner", default=ORPHAN_OWNER)
    parser.add_argument("--apply", action="store_true", help="默认 dry-run；--apply 才回填")
    parser.add_argument("--report", default="", help="JSON 报告路径；默认写入 data/migrations/ 时间戳文件")
    args = parser.parse_args(argv)

    client, cfg = build_client()
    collections = resolve_collections(client, cfg, args.collection or None)
    if not collections:
        raise SystemExit("没有可处理的集合")

    mode = "APPLY" if args.apply else "DRY-RUN"
    try:
        report, warnings = run(client, collections, apply=args.apply,
                               default_owner=args.default_owner)
    except RuntimeError as err:
        print(str(err), file=sys.stderr)
        return 2

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    if args.report:
        out_path = Path(args.report)
    else:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = PROJECT_ROOT / "data" / "migrations" / f"qdrant-owner-report-{ts}.json"
    write_report(report, out_path)

    # 输出方案要求的校验行
    scanned = report["scanned"]
    updated = report["updated"]
    conflicts = report["conflicts"]
    unowned = sum(c["unowned"] for c in report["collections"].values())
    print(f"mode={mode} scanned={scanned} updated={updated} "
          f"conflicts={conflicts} unowned={unowned} report={out_path}")
    for name, c in report["collections"].items():
        print(f"  {name}: points={c['points']} unowned={c['unowned']} "
              f"changed={c['changed']} skipped={c['skipped']} conflicts={c['conflicts']}")

    if args.apply:
        # 迁移后复跑 dry-run 校验
        verify, warns = run(client, collections, apply=False, default_owner=args.default_owner)
        vc = verify["conflicts"]
        vu = sum(c["unowned"] for c in verify["collections"].values())
        vch = sum(c["changed"] for c in verify["collections"].values())
        ok = (vch == 0 and vc == 0 and vu == 0)
        print(f"recheck changed={vch} conflicts={vc} unowned={vu} -> "
              f"{'OK' if ok else 'FAILED'}")
        if not ok:
            return 1

    return 1 if conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
