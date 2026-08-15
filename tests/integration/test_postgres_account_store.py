"""PostgresAccountStore 集成测试：需 POSTGRES_TEST_DSN（否则 skip）。"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from careercrew_api.auth.store import AccountExistsError, PostgresAccountStore, hash_token

pytestmark = pytest.mark.integration

DSN = os.environ.get("POSTGRES_TEST_DSN", "").strip()

pytestmark_skip = pytest.mark.skipif(
    not DSN, reason="POSTGRES_TEST_DSN not set"
)


def _require_disposable_db(dsn: str) -> None:
    """安全闸：集成测试会清空 auth 表，只允许指向一次性测试库。"""
    from urllib.parse import urlparse

    dbname = urlparse(dsn.replace("postgresql://", "postgres://")).path.lstrip("/")
    if dbname == "careercrew":
        raise RuntimeError(
            "POSTGRES_TEST_DSN 指向生产库 careercrew，拒绝运行（会清空账号表）。"
            "请使用 careercrew_test 等一次性测试库。"
        )


@pytest.fixture
def store():
    _require_disposable_db(DSN)
    store = PostgresAccountStore(DSN)
    with store._connect() as conn, conn.transaction():
        conn.execute("DELETE FROM auth_refresh_sessions")
        conn.execute("DELETE FROM auth_login_attempts")
        conn.execute("DELETE FROM admin_audit_events")
        conn.execute("DELETE FROM auth_accounts")
    yield store
    with store._connect() as conn, conn.transaction():
        conn.execute("DELETE FROM auth_refresh_sessions")
        conn.execute("DELETE FROM auth_login_attempts")
        conn.execute("DELETE FROM admin_audit_events")
        conn.execute("DELETE FROM auth_accounts")


@pytest.mark.skipif(not DSN, reason="POSTGRES_TEST_DSN not set")
def test_postgres_roundtrip_and_guards(store):
    admin = store.create_first_admin("admin", "$argon2$fake")
    assert admin["id"] == "u_001"
    assert store.account_by_username("admin")["token_version"] == 0
    assert store.bump_token_version("u_001") == 1
    member = store.create_account("member", "$argon2$fake2", "user")
    with pytest.raises(AccountExistsError):
        store.create_account("member", "$argon2$fake3", "user")
    now = datetime.now(UTC)
    store.create_refresh_session("r1", member["id"], now + timedelta(days=1))
    assert store.revoke_all_refresh_sessions(member["id"]) == 1
    assert store.rotate_refresh_session("r1", "r2", now + timedelta(days=1)) is None
    store.add_audit_event("u_001", "user.create", member["id"], {"role": "user"})
    items, total = store.list_accounts(0, 10)
    assert total == 2 and items[0]["id"] == "u_001"
    assert "password_hash" not in items[0]
    # 限速：5 次失败后锁定
    key = "login:ip:1.2.3.4"
    for i in range(1, 6):
        locked, _ = store.record_login_failure(
            key, max_failures=5, window=timedelta(minutes=15), lock=timedelta(minutes=15)
        )
        assert locked == (i >= 5)
    store.clear_login_failures(key)


@pytest.mark.skipif(not DSN, reason="POSTGRES_TEST_DSN not set")
def test_postgres_rotate_rejects_disabled_and_expired(store):
    store.create_first_admin("admin", "$argon2$fake")
    now = datetime.now(UTC)
    store.create_refresh_session("active", "u_001", now + timedelta(days=1))
    store.create_refresh_session("expired", "u_001", now - timedelta(minutes=1))
    assert store.rotate_refresh_session("expired", "x1", now + timedelta(days=1)) is None
    store.update_account("u_001", status="disabled")
    assert store.rotate_refresh_session("active", "x2", now + timedelta(days=1)) is None


@pytest.mark.skipif(not DSN, reason="POSTGRES_TEST_DSN not set")
def test_postgres_delete_expired_refresh_sessions(store):
    store.create_first_admin("admin", "$argon2$fake")
    now = datetime.now(UTC)
    store.create_refresh_session("expired", "u_001", now - timedelta(minutes=1))
    store.create_refresh_session("alive", "u_001", now + timedelta(days=1))
    store.create_refresh_session("old-revoked", "u_001", now + timedelta(days=1))
    store.revoke_refresh_session("old-revoked")
    with store._connect() as conn, conn.transaction():
        conn.execute(
            "UPDATE auth_refresh_sessions SET revoked_at = %s WHERE token_hash = %s",
            (now - timedelta(days=60), hash_token("old-revoked")),
        )
    deleted = store.delete_expired_refresh_sessions(revoked_older_than_days=30)
    assert deleted == 2
    with store._connect() as conn:
        remaining = {r["token_hash"] for r in conn.execute("SELECT token_hash FROM auth_refresh_sessions")}
    assert remaining == {hash_token("alive")}


@pytest.mark.skipif(not DSN, reason="POSTGRES_TEST_DSN not set")
def test_postgres_accepts_quality_reviewer_role(store):
    store.create_first_admin("admin", "$argon2$fake")
    member = store.create_account("member", "$argon2$fake2", "user")
    # 写入/读出 quality_reviewer
    updated = store.update_account(member["id"], role="quality_reviewer")
    assert updated["role"] == "quality_reviewer"
    assert store.account_by_id(member["id"])["role"] == "quality_reviewer"
    # 其余任意字符串一律拒绝（ValueError，与 update_account 现状一致）
    with pytest.raises(ValueError, match="invalid role"):
        store.update_account(member["id"], role="superuser")


@pytest.mark.skipif(not DSN, reason="POSTGRES_TEST_DSN not set")
def test_postgres_role_migration_is_idempotent(store):
    """迁移幂等：对已有旧约束的库重复执行不报错，且 CHECK 约束放开 quality_reviewer。"""
    # 模拟旧约束：先 DROP 新约束并恢复旧 CHECK（admin/user），再重建 store 触发迁移。
    with store._connect() as conn, conn.transaction():
        conn.execute("ALTER TABLE auth_accounts DROP CONSTRAINT IF EXISTS auth_accounts_role_check")
        conn.execute(
            "ALTER TABLE auth_accounts ADD CONSTRAINT auth_accounts_role_check "
            "CHECK (role IN ('admin','user'))"
        )
    # 重建 store 会执行迁移（DROP 旧约束 + ADD 新的含 quality_reviewer）
    migrated = PostgresAccountStore(DSN)
    # 迁移后 quality_reviewer 写入成功
    migrated.create_first_admin("admin2", "$argon2$fake")
    member = migrated.create_account("member2", "$argon2$fake2", "user")
    updated = migrated.update_account(member["id"], role="quality_reviewer")
    assert updated["role"] == "quality_reviewer"
    # 再次重建（重复迁移）不报错
    PostgresAccountStore(DSN)

