"""verify_qdrant_ownership：owner 迁移校验 + snapshot + JSON 迁移报告。

覆盖验收点：
- dry-run 不改数据；
- apply 后复跑 dry-run 全 0；
- 冲突点不被覆盖且计入 conflicts；
- snapshot 失败时 apply 中止、dry-run 告警继续；
- 报告 JSON 字段齐全。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from verify_qdrant_ownership import (  # noqa: E402
    ORPHAN_OWNER,
    _classify_point,
    build_report,
    snapshot_collection,
    verify_collection,
)


class FakePoint:
    def __init__(self, id, payload):
        self.id = id
        self.payload = payload


class FakeClient:
    """内存版 QdrantClient 替身：scroll / set_payload / create_snapshot。"""

    def __init__(self, collection_points: dict[str, list[FakePoint]],
                 snapshotable: bool = True):
        self._collections = collection_points
        self._snapshotable = snapshotable
        self.set_payload_calls: list[tuple] = []
        self.snapshot_calls: list[str] = []
        self.create_snapshot_calls: list[tuple] = []

    def get_collection(self, name):
        return self._collections[name]

    def scroll(self, collection, limit=0, offset=None,
               with_payload=True, with_vectors=False):
        points = self._collections[collection]
        return list(points), None

    def set_payload(self, collection, payload, points):
        self.set_payload_calls.append((collection, dict(payload), list(points)))
        for pid in points:
            for p in self._collections[collection]:
                if p.id == pid:
                    merged = dict(p.payload or {})
                    for k, v in payload.items():
                        if v is None:
                            merged.pop(k, None)
                        else:
                            merged[k] = v
                    p.payload = merged

    def create_snapshot(self, collection_name):
        self.create_snapshot_calls.append(collection_name)
        if not self._snapshotable:
            raise RuntimeError("snapshot failed")
        import uuid

        return uuid.uuid4().hex

    def create_full_snapshot(self):
        if not self._snapshotable:
            raise RuntimeError("snapshot failed")
        import uuid

        return uuid.uuid4().hex


def _mk(payload: dict | None) -> FakePoint:
    return FakePoint(id=f"p-{len(payload or {})}-{abs(hash(json.dumps(payload, sort_keys=True, default=str)))}", payload=payload)


class FailingSetPayloadClient(FakeClient):
    """set_payload 总是抛异常，用于验证 apply 失败计入 unresolved。"""

    def __init__(self, collection_points, **kwargs):
        super().__init__(collection_points, **kwargs)
        self.failed_set_payload_calls = 0

    def set_payload(self, collection, payload, points):
        self.failed_set_payload_calls += 1
        raise RuntimeError("set_payload failed")


# ── 纯函数：分类逻辑 ──


def test_classify_owned_knowledge():
    assert _classify_point({"owner_user_id": "u_001"}, "owner_user_id") == "owned"


def test_classify_owned_episodic_by_user_id():
    assert _classify_point({"user_id": "u_001"}, "user_id") == "owned"


def test_classify_orphan():
    assert _classify_point({}, "owner_user_id") == "orphan"
    assert _classify_point({"type": "x"}, "user_id") == "orphan"


def test_classify_owned_by_owner_when_episodic_user_id_absent():
    # episodic 点带 owner_user_id（前一轮回填）也算 owned
    assert _classify_point({"owner_user_id": "u_001"}, "user_id") == "owned"


# ── dry-run / apply 语义 ──


def test_verify_dryrun_no_write():
    pts = [FakePoint("p1", {}), FakePoint("p2", {}), FakePoint("p3", {"owner_user_id": "u_001"})]
    client = FakeClient({"c": pts})
    scanned, unowned, changed, skipped, conflicts, unresolved = verify_collection(
        client, "c", "owner_user_id", apply=False, default_owner="u_001"
    )
    assert (scanned, unowned, changed, skipped, conflicts, unresolved) == (3, 2, 2, 1, 0, 0)
    assert client.set_payload_calls == []  # dry-run 不写
    assert pts[0].payload == {} and pts[1].payload == {}


def test_verify_apply_backfills_and_rerun_all_zero():
    pts = [FakePoint("p1", {}), FakePoint("p2", {}), FakePoint("p3", {"owner_user_id": "u_001"})]
    client = FakeClient({"c": pts})
    scanned, unowned, changed, skipped, conflicts, unresolved = verify_collection(
        client, "c", "owner_user_id", apply=True, default_owner="u_001"
    )
    assert (scanned, unowned, changed, skipped, conflicts, unresolved) == (3, 2, 2, 1, 0, 0)
    assert pts[0].payload == {"owner_user_id": ORPHAN_OWNER}
    assert pts[1].payload == {"owner_user_id": ORPHAN_OWNER}
    # 复跑：全 0
    scanned2, unowned2, changed2, skipped2, conflicts2, unresolved2 = verify_collection(
        client, "c", "owner_user_id", apply=True, default_owner="u_001"
    )
    assert (scanned2, unowned2, changed2, skipped2, conflicts2, unresolved2) == (3, 0, 0, 3, 0, 0)


def test_verify_conflict_not_overwritten():
    # 已有 owner_user_id 且不等于 default-owner → 冲突，不覆盖
    pts = [FakePoint("p1", {"owner_user_id": "u_999"})]
    client = FakeClient({"c": pts})
    scanned, unowned, changed, skipped, conflicts, unresolved = verify_collection(
        client, "c", "owner_user_id", apply=True, default_owner="u_001"
    )
    assert (scanned, unowned, changed, skipped, conflicts, unresolved) == (1, 0, 0, 0, 1, 0)
    assert client.set_payload_calls == []
    assert pts[0].payload["owner_user_id"] == "u_999"  # 未被覆盖


def test_verify_conflict_with_non_default_owner():
    # 非默认 --default-owner：另一 owner 为冲突，默认值本身不作 magic 豁免
    pts = [FakePoint("p1", {"owner_user_id": "u_001"})]
    client = FakeClient({"c": pts})
    scanned, unowned, changed, skipped, conflicts, unresolved = verify_collection(
        client, "c", "owner_user_id", apply=True, default_owner="u_999"
    )
    # owner=u_001 != default u_999 → 冲突；无孤儿，不写
    assert (scanned, unowned, changed, skipped, conflicts, unresolved) == (1, 0, 0, 0, 1, 0)
    assert client.set_payload_calls == []
    assert pts[0].payload["owner_user_id"] == "u_001"


def test_verify_apply_set_payload_failure_counts_unresolved():
    # apply 时 set_payload 抛异常 → 计入 unresolved 而非 changed，且继续跑完
    pts = [FakePoint("p1", {"owner_user_id": "u_999"}), FakePoint("p2", {})]
    broken = FailingSetPayloadClient({"c": pts})
    scanned, unowned, changed, skipped, conflicts, unresolved = verify_collection(
        broken, "c", "owner_user_id", apply=True, default_owner="u_001"
    )
    assert (scanned, unowned, changed, skipped, conflicts, unresolved) == (2, 1, 0, 0, 1, 1)
    # 回填失败的点未被写入
    assert pts[1].payload == {}

    # 同一集合（apply 时）reported unresolved 与 conflicts 各自独立
    report = build_report(
        {}, {"c": {"key_field": "owner_user_id", "points": scanned, "unowned": unowned,
                   "changed": changed, "skipped": skipped, "conflicts": conflicts,
                   "unresolved": unresolved}},
        "2025-01-01T00:00:00+00:00", "2025-01-01T00:00:05+00:00", "APPLY",
    )
    assert report["conflicts"] == 1
    assert report["unresolved"] == 1


# ── snapshot ──


def test_snapshot_collection_success():
    client = FakeClient({})
    name = snapshot_collection(client, "c")
    assert name is not None
    assert client.create_snapshot_calls == ["c"]


def test_snapshot_collection_failure_returns_none():
    client = FakeClient({}, snapshotable=False)
    assert snapshot_collection(client, "c") is None


# ── 报告字段齐全 ──


def test_build_report_has_required_fields():
    per_collection = {
        "careercrew_mm": {
            "key_field": "owner_user_id", "points": 211,
            "unowned": 0, "changed": 0, "skipped": 211, "conflicts": 0,
        },
        "careercrew_episodic_v2": {
            "key_field": "user_id", "points": 14,
            "unowned": 0, "changed": 0, "skipped": 14, "conflicts": 0,
        },
    }
    report = build_report(
        {"careercrew_mm": "snap1", "careercrew_episodic_v2": "snap2"},
        per_collection, "2025-01-01T00:00:00+00:00",
        "2025-01-01T00:00:05+00:00", "DRY-RUN",
    )
    required = {"snapshot_id", "scanned", "updated", "conflicts",
                "unresolved", "started_at", "finished_at"}
    assert required <= set(report.keys())
    assert report["scanned"] == 225
    assert report["updated"] == 0
    assert report["conflicts"] == 0
    assert report["unresolved"] == 0
    assert list(report["collections"]) == ["careercrew_mm", "careercrew_episodic_v2"]

