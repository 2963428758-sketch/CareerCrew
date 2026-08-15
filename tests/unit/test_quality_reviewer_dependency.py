"""quality_reviewer 依赖 require_quality_reviewer 与 JWT role claim 单元测试。

依赖直接以 user dict 调用（Phase 5 才建端点），验证校验语义：
- reviewer 通过、admin 不自动满足、普通 user 被拒（403）。
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from careercrew_api.auth.dependencies import require_admin, require_quality_reviewer
from careercrew_api.auth.service import AuthService
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


def _token_for(svc: AuthService, username: str, password: str = PASSWORD) -> str:
    payload, _ = svc.login(username, password)
    return payload["access_token"]


def test_require_quality_reviewer_accepts_reviewer(service):
    admin = service.current_user(_token_for(service, "admin"))
    reviewer = service.create_user(admin, "reviewer", USER_PASSWORD, "quality_reviewer")
    user_dict = {"id": reviewer["id"], "username": "reviewer", "role": "quality_reviewer"}
    assert require_quality_reviewer(user_dict) == user_dict


def test_require_quality_reviewer_rejects_user_and_admin(service):
    # 普通 user
    with pytest.raises(HTTPException) as err_user:
        require_quality_reviewer({"id": "u", "username": "u", "role": "user"})
    assert err_user.value.status_code == 403
    assert "quality reviewer required" in str(err_user.value.detail)

    # admin 不自动满足（方案：admin 对质量指标是"可选只读"，由 Phase 5 端点自行放行）
    with pytest.raises(HTTPException) as err_admin:
        require_quality_reviewer({"id": "a", "username": "a", "role": "admin"})
    assert err_admin.value.status_code == 403


def test_reviewer_is_rejected_by_require_admin(service):
    admin = service.current_user(_token_for(service, "admin"))
    reviewer = service.create_user(admin, "reviewer", USER_PASSWORD, "quality_reviewer")
    user_dict = {"id": reviewer["id"], "username": "reviewer", "role": "quality_reviewer"}
    with pytest.raises(HTTPException) as err:
        require_admin(user_dict)
    assert err.value.status_code == 403
    assert "administrator required" in str(err.value.detail)


def test_reviewer_login_token_has_quality_reviewer_role_claim(service):
    admin = service.current_user(_token_for(service, "admin"))
    service.create_user(admin, "reviewer", USER_PASSWORD, "quality_reviewer")

    payload, _ = service.login("reviewer", USER_PASSWORD)
    user = payload["user"]
    assert user["role"] == "quality_reviewer"

    # 校验 JWT role claim 路径无需改动：claim == 新角色，且 current_user 校验通过
    current = service.current_user(payload["access_token"])
    assert current["role"] == "quality_reviewer"
    assert current["username"] == "reviewer"
