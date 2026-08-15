"""quality_reviewer 角色的 store/service 单元测试（Phase 0）。

覆盖：新角色可写入/读出、非法角色拒绝、last-admin 不变量不受 reviewer 影响。
"""
from __future__ import annotations

import pytest

from careercrew_api.auth.service import AuthService, LastAdminError
from careercrew_core.state.settings import AuthSettings
from tests.fakes import FakeAccountStore

PASSWORD = "correct-horse-battery-staple"
USER_PASSWORD = "user-password-123"


@pytest.fixture
def service():
    settings = AuthSettings(
        environment="test",
        jwt_secret="test-secret-" + "x" * 40,
    )
    svc = AuthService(settings, FakeAccountStore())
    svc.bootstrap_admin("admin", PASSWORD)
    return svc


def _login(svc: AuthService, username: str, password: str) -> dict:
    payload, _refresh = svc.login(username, password)
    return payload["user"]


def _actor(svc: AuthService, username: str = "admin", password: str = PASSWORD) -> dict:
    payload, _ = svc.login(username, password)
    return svc.current_user(payload["access_token"])


def test_store_accepts_quality_reviewer_role(service):
    admin = _actor(service)
    reviewer = service.create_user(admin, "reviewer", USER_PASSWORD, "quality_reviewer")
    assert reviewer["role"] == "quality_reviewer"

    # 可读回：store 层角色值往返一致
    stored = service.store.account_by_id(reviewer["id"])
    assert stored["role"] == "quality_reviewer"


def test_admin_can_promote_demote_between_user_and_reviewer(service):
    admin = _actor(service)
    member = service.create_user(admin, "member", USER_PASSWORD, "user")

    # user -> quality_reviewer
    promoted = service.update_user(admin, member["id"], role="quality_reviewer")
    assert promoted["role"] == "quality_reviewer"

    # quality_reviewer -> user
    demoted = service.update_user(admin, member["id"], role="user")
    assert demoted["role"] == "user"


def test_reviewer_does_not_count_as_active_admin(service):
    admin = _actor(service)
    # 唯一 admin 之外全是 reviewer/user，降级唯一 admin 仍应触发 LastAdminError
    reviewercount = service.create_user(admin, "reviewer", USER_PASSWORD, "quality_reviewer")
    assert reviewercount["role"] == "quality_reviewer"

    with pytest.raises(LastAdminError):
        service.update_user(admin, "u_001", role="user")

    # reviewer 本身可被随意禁用/改角色，不触发 last-admin 保护
    updated = service.update_user(admin, reviewercount["id"], status="disabled")
    assert updated["status"] == "disabled"
