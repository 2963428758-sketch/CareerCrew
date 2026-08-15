"""过期/长期吊销刷新会话清理。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from careercrew_api.auth.store import SqliteAccountStore, hash_token


def test_delete_expired_and_old_revoked_sessions_only(tmp_path):
    store = SqliteAccountStore(str(tmp_path / "accounts.db"))
    store.create_first_admin("admin", "$argon2$fake")
    now = datetime.now(UTC)
    store.create_refresh_session("expired", "u_001", now - timedelta(minutes=1))
    store.create_refresh_session("alive", "u_001", now + timedelta(days=1))
    store.create_refresh_session("old-revoked", "u_001", now + timedelta(days=1))
    store.revoke_refresh_session("old-revoked")
    # 手动把 revoked_at 改成 60 天前（绕过刚写入的时间戳）
    with store._connect() as conn:
        conn.execute(
            "UPDATE refresh_sessions SET revoked_at = ? WHERE token_hash = ?",
            ((now - timedelta(days=60)).isoformat(), hash_token("old-revoked")),
        )
    deleted = store.delete_expired_refresh_sessions(revoked_older_than_days=30)
    assert deleted == 2
    with store._connect() as conn:
        remaining = {r["token_hash"] for r in conn.execute("SELECT token_hash FROM refresh_sessions")}
    assert remaining == {hash_token("alive")}
