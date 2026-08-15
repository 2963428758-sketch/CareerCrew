"""AccountStore SQLite 实现：状态/令牌版本/会话撤销/限速/审计。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from careercrew_api.auth.store import AccountExistsError, SqliteAccountStore, hash_token


PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fake$fake"


@pytest.fixture
def store(tmp_path):
    return SqliteAccountStore(str(tmp_path / "accounts.db"))


def test_create_first_admin_and_token_version_fields(store):
    assert not store.has_accounts()
    admin = store.create_first_admin("admin", PASSWORD_HASH)
    assert admin["id"] == "u_001" and admin["role"] == "admin"
    row = store.account_by_username("admin")
    assert row["status"] == "active" and row["token_version"] == 0
    assert "password_hash" not in store.account_by_id("u_001")


def test_bump_token_version_and_update_account(store):
    store.create_first_admin("admin", PASSWORD_HASH)
    assert store.bump_token_version("u_001") == 1
    updated = store.update_account("u_001", status="disabled")
    assert updated["status"] == "disabled"
    assert store.account_by_id("u_001")["token_version"] == 1


def test_revoke_other_and_all_refresh_sessions(store):
    store.create_first_admin("admin", PASSWORD_HASH)
    now = datetime.now(UTC)
    store.create_refresh_session("t1", "u_001", now + timedelta(days=1))
    store.create_refresh_session("t2", "u_001", now + timedelta(days=1))
    revoked = store.revoke_other_refresh_sessions("u_001", "t1")
    assert revoked == 1
    assert store.rotate_refresh_session("t2", "t3", now + timedelta(days=1)) is None
    assert store.rotate_refresh_session("t1", "t4", now + timedelta(days=1)) is not None
    assert store.revoke_all_refresh_sessions("u_001") == 1


def test_duplicate_username_raises(store):
    store.create_first_admin("admin", PASSWORD_HASH)
    with pytest.raises(AccountExistsError):
        store.create_account("admin", PASSWORD_HASH, "user")


def test_rotate_refresh_session_rejects_disabled_account(store):
    store.create_first_admin("admin", PASSWORD_HASH)
    now = datetime.now(UTC)
    store.create_refresh_session("t1", "u_001", now + timedelta(days=1))
    store.update_account("u_001", status="disabled")
    assert store.rotate_refresh_session("t1", "t2", now + timedelta(days=1)) is None


def test_login_failure_window_and_lock(store):
    now = datetime.now(UTC)
    key = "login:u:admin"
    for i in range(1, 6):
        locked, _ = store.record_login_failure(
            key, max_failures=5, window=timedelta(minutes=15), lock=timedelta(minutes=15)
        )
        assert locked == (i >= 5)
    locked, locked_until = store.record_login_failure(
        key, max_failures=5, window=timedelta(minutes=15), lock=timedelta(minutes=15)
    )
    assert locked and locked_until is not None
    store.clear_login_failures(key)
    locked, _ = store.record_login_failure(
        key, max_failures=5, window=timedelta(minutes=15), lock=timedelta(minutes=15)
    )
    assert not locked
