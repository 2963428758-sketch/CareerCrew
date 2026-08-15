"""PostgresAccountStore 集成测试：需 POSTGRES_TEST_DSN（否则 skip）。"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from careercrew_api.auth.store import AccountExistsError, PostgresAccountStore

pytestmark = pytest.mark.integration

DSN = os.environ.get("POSTGRES_TEST_DSN", "").strip()

pytestmark_skip = pytest.mark.skipif(
    not DSN, reason="POSTGRES_TEST_DSN not set"
)


@pytest.fixture
def store():
    store = PostgresAccountStore(DSN)
    with store._connect() as conn, conn.transaction():
        conn.execute("DELETE FROM auth_refresh_sessions")
        conn.execute("DELETE FROM auth_login_attempts")
        conn.execute("DELETE FROM admin_audit_events")
        conn.execute("DELETE FROM auth_accounts")
    return store


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
