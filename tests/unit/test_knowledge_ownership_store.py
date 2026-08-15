"""知识库所有权过滤的生产存储集成测试（Finding 2 修复）。

FakeRuntime 只覆盖握手里的 ``knowledge_docs_by_user`` 字典过滤，从不触碰生产
``CareerCrewRuntime`` 委托给真实 ``store.list_docs(filters=...)`` /
``store.delete_by_metadata(...)`` 的所有权链路。若真实链路的 owner 过滤键名
（``owner_user_id`` vs ``user_id``）或 ``__access_user`` should-表达式（public OR own）
回归，FakeRuntime 测试仍会保持绿色。

本文件钉住这条生产 seam：
- 用**真实** ``QdrantStore``（`:memory:` 本地模式，与 test_ingestion_pipeline.py
  一致）播种用户 A / B 的私有文档 + A 的公共文档；
- 直接调用生产 ``CareerCrewRuntime`` 的 ``_knowledge_scope_filters`` /
  ``knowledge_status`` / ``delete_document``（以 ``_initialized=True`` + 真实 store
  的轻量实例规避重组件初始化，不 mock 过滤逻辑本身）。

这样一条 ``owner_user_id`` 键名错配或 ``__access_user`` 序列化回归会在此处失败，
而不是只在 FakeRuntime 的单测里保持绿色。
"""
from __future__ import annotations

import pytest

from careercrew_ai.vector_store.base_vector_store import VectorRecord
from careercrew_ai.vector_store.qdrant_store import QdrantStore
from careercrew_core.state.settings import Settings


def _runtime_with_real_store(valid_config_data: dict):
    """构造一个只装载真实 QdrantStore 的轻量 runtime（不动重组件）。"""
    from careercrew_api.runtime import CareerCrewRuntime

    store = QdrantStore(Settings.model_validate(valid_config_data))
    rt = CareerCrewRuntime()
    rt._initialized = True
    rt.store = store
    return rt, store


def _record(doc: str, owner: str, visibility: str) -> VectorRecord:
    """一条单点知识文档，metadata 与生产 upsert 的 owner/visibility 键一致。"""
    return VectorRecord(
        id=f"{doc}-p0", dense=[0.1] * 1024, text="正文内容",
        metadata={"doc": doc, "source": f"{doc}.md", "category": "knowledge",
                  "owner_user_id": owner, "visibility": visibility},
    )


def _seed(store: QdrantStore) -> None:
    store.upsert([
        _record("alice-private", "u_A", "private"),
        _record("alice-public", "u_A", "public"),
        _record("bob-private", "u_B", "private"),
    ])


def test_knowledge_status_hides_other_users_private_docs(valid_config_data: dict):
    """生产 runtime + 真实 store：B 只能看到自己的私有 + 所有 public。"""
    rt, store = _runtime_with_real_store(valid_config_data)
    _seed(store)

    alice_docs = {d["doc"] for d in rt.knowledge_status("u_A")["docs"]}
    bob_docs = {d["doc"] for d in rt.knowledge_status("u_B")["docs"]}
    public_docs = {d["doc"] for d in rt.knowledge_status("u_B", scope="public")["docs"]}
    private_docs = {d["doc"] for d in rt.knowledge_status("u_A", scope="private")["docs"]}

    assert alice_docs == {"alice-private", "alice-public"}
    assert bob_docs == {"alice-public", "bob-private"}
    assert "alice-private" not in bob_docs
    assert "bob-private" not in alice_docs
    assert public_docs == {"alice-public"}
    # private scope 按 owner_user_id 过滤（不含他人 private；本人 public 同名仍归属本人）
    assert private_docs == {"alice-private", "alice-public"}
    assert "bob-private" not in private_docs


def test_delete_document_noop_for_other_users_private_doc(valid_config_data: dict):
    """B 删除 A 的 private 文档：deleted==0, public_blocked=False，且数据原样。"""
    rt, store = _runtime_with_real_store(valid_config_data)
    _seed(store)

    before = store.list_docs()

    deleted, public_blocked = rt.delete_document("u_B", "alice-private")
    assert deleted == 0
    assert public_blocked is False

    after = store.list_docs()
    # A 的文档逐条不变（而非仅"仍在"）——B 的删除必须是彻底的 no-op
    assert after == before
    assert {d["doc"] for d in after} == {"alice-private", "alice-public", "bob-private"}


def test_delete_document_owner_can_delete_own_private(valid_config_data: dict):
    """A 删除自己的私有文档：确实删除该点，且不波及其他用户/public。"""
    rt, store = _runtime_with_real_store(valid_config_data)
    _seed(store)

    deleted, public_blocked = rt.delete_document("u_A", "alice-private")
    assert deleted == 1
    assert public_blocked is False

    remaining = {d["doc"] for d in store.list_docs()}
    assert remaining == {"alice-public", "bob-private"}


def test_delete_document_public_blocked_for_non_admin(valid_config_data: dict):
    """非 admin 删除 public 文档：不删，返回 public_blocked=True。"""
    rt, store = _runtime_with_real_store(valid_config_data)
    _seed(store)

    deleted, public_blocked = rt.delete_document("u_B", "alice-public")
    assert deleted == 0
    assert public_blocked is True
    assert {d["doc"] for d in store.list_docs()} == {
        "alice-private", "alice-public", "bob-private",
    }


@pytest.mark.parametrize("scope,expected", [
    ("public", {"visibility": "public"}),
    ("private", {"owner_user_id": "u_A"}),
    ("all", {"__access_user": "u_A"}),
])
def test_knowledge_scope_filters_shape(scope: str, expected: dict):
    """生产 filter 构造的键名/值逐字段断言（owner_user_id 键名错配会在此暴露）。"""
    from careercrew_api.runtime import CareerCrewRuntime

    assert CareerCrewRuntime._knowledge_scope_filters("u_A", scope) == expected
