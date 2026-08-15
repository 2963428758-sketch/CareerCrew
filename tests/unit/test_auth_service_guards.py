"""AuthService 守卫与令牌版本语义（SQLite store，纯单元）。"""
from __future__ import annotations

import pytest

from careercrew_api.auth.service import (
    AuthService,
    AuthenticationError,
    LastAdminError,
    LoginLockedError,
    SelfAdminError,
)
from careercrew_core.state.settings import AuthSettings
from tests.fakes import FakeAccountStore

PASSWORD = "correct-horse-battery-staple"
USER_PASSWORD = "user-password-123"  # 满足新密码策略（字母+数字）


@pytest.fixture
def service():
    settings = AuthSettings(
        environment="test",
        jwt_secret="test-secret-" + "x" * 40,
    )
    store = FakeAccountStore()
    svc = AuthService(settings, store)
    svc.bootstrap_admin("admin", PASSWORD)
    return svc


def _login(svc: AuthService, username: str, password: str = PASSWORD):
    payload, refresh = svc.login(username, password)
    return payload["access_token"], refresh


def test_disable_user_kills_access_and_refresh_immediately(service):
    admin_actor = service.current_user(_login(service, "admin")[0])
    member = service.create_user(admin_actor, "member", USER_PASSWORD, "user")
    access, _ = _login(service, "member", USER_PASSWORD)
    assert service.current_user(access)["username"] == "member"
    service.update_user(admin_actor, member["id"], status="disabled")
    with pytest.raises(AuthenticationError):
        service.current_user(access)


def test_admin_cannot_disable_or_demote_self(service):
    # 存在第二个 admin 时，自我修改被 SelfAdmin 拒绝（不会触犯最后管理员不变量）
    admin = service.current_user(_login(service, "admin")[0])
    service.create_user(admin, "second", USER_PASSWORD, "admin")
    with pytest.raises(SelfAdminError):
        service.update_user(admin, "u_001", status="disabled")
    with pytest.raises(SelfAdminError):
        service.update_user(admin, "u_001", role="user")


def test_cannot_lose_last_active_admin(service):
    admin = service.current_user(_login(service, "admin")[0])
    # 唯一 admin：系统级不变量优先于 self 限制
    with pytest.raises(LastAdminError):
        service.update_user(admin, "u_001", status="disabled")
    with pytest.raises(LastAdminError):
        service.update_user(admin, "u_001", role="user")
    # 有第二个 admin 后，第一个 admin 可被对方禁用
    second = service.create_user(admin, "second", USER_PASSWORD, "admin")
    actor2 = service.current_user(_login(service, "second", USER_PASSWORD)[0])
    updated = service.update_user(actor2, "u_001", status="disabled")
    assert updated["status"] == "disabled"
    # 只剩 second 一个有效 admin：不能再自毁
    with pytest.raises(LastAdminError):
        service.update_user(actor2, second["id"], status="disabled")


def test_create_user_default_password_forces_change(service):
    admin_actor = service.current_user(_login(service, "admin")[0])
    member = service.create_user(admin_actor, "fresh", None, "user")  # 默认密码 123456
    access, _ = _login(service, "fresh", "123456")
    user = service.current_user(access)
    assert user["username"] == "fresh"
    assert user["must_change_password"] is True
    # 强制改密：免输旧密码，改完标记清除
    service.change_own_password(user, "", USER_PASSWORD)
    fresh, _ = _login(service, "fresh", USER_PASSWORD)
    assert service.current_user(fresh)["must_change_password"] is False


def test_password_policy_rejects_weak_new_password(service):
    service.create_user(service.current_user(_login(service, "admin")[0]),
                        "weak", USER_PASSWORD, "user")
    access, _ = _login(service, "weak", USER_PASSWORD)
    user = service.current_user(access)
    with pytest.raises(ValueError, match="8-64"):
        service.change_own_password(user, USER_PASSWORD, "123456")  # 太短
    with pytest.raises(ValueError, match="8-64"):
        service.change_own_password(user, USER_PASSWORD, "abcdefgh")  # 无数字


def test_change_own_password_revokes_other_sessions(service):
    access, refresh = _login(service, "admin")
    other_access, other_refresh = _login(service, "admin")
    service.change_own_password(
        service.current_user(access), PASSWORD, "new-password-123456", current_refresh_token=refresh
    )
    with pytest.raises(AuthenticationError):
        service.current_user(access)  # 旧 access 因 tv bump 失效
    with pytest.raises(AuthenticationError):
        service.refresh(other_refresh)  # 其他刷新会话被撤销
    new_access, _ = _login(service, "admin", "new-password-123456")
    assert service.current_user(new_access)["username"] == "admin"


def test_login_lock_after_repeated_failures(service):
    for _ in range(service.settings.login_max_failures - 1):
        with pytest.raises(AuthenticationError):
            service.login("admin", "wrong-password-123")
    with pytest.raises(LoginLockedError):
        service.login("admin", "wrong-password-123")
    with pytest.raises(LoginLockedError):
        service.login("admin", PASSWORD)
