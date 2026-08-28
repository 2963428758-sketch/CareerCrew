"""测试用户个性化设置与 API Key 接口 (GET/PUT/DELETE/POST /api/settings/apikey)。"""
from __future__ import annotations

import pytest


@pytest.mark.web
def test_apikey_settings_crud_lifecycle(client):
    """测试 API Key 的完整生命周期：默认无 Key -> 保存 -> 查询 -> 清除。"""
    # 1. 初始查询：默认无个人 key
    resp = client.get("/api/settings/apikey")
    assert resp.status_code == 200
    data = resp.json()
    assert "has_key" in data
    assert data["provider"] == "dashscope"

    # 2. 空 key 更新校验
    bad_resp = client.put("/api/settings/apikey", json={"api_key": "   "})
    assert bad_resp.status_code == 400

    # 3. 设置有效 key
    test_key = "sk-0123456789abcdef0123456789abcdef"
    put_resp = client.put("/api/settings/apikey", json={"api_key": test_key})
    assert put_resp.status_code == 200
    put_data = put_resp.json()
    assert put_data["ok"] is True
    assert "masked_key" in put_data
    assert "sk-0" in put_data["masked_key"]
    assert "cdef" in put_data["masked_key"]

    # 4. 再次查询：应显示 has_key=True，且返回脱敏掩码
    get_resp = client.get("/api/settings/apikey")
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data["has_key"] is True
    assert get_data["masked_key"] == put_data["masked_key"]

    # 5. 清除 key
    del_resp = client.delete("/api/settings/apikey")
    assert del_resp.status_code == 200
    assert del_resp.json()["ok"] is True

    # 6. 清除后再查：恢复 has_key=False
    final_resp = client.get("/api/settings/apikey")
    assert final_resp.status_code == 200
    assert final_resp.json()["has_key"] is False


@pytest.mark.web
def test_apikey_connectivity_test_endpoint(client):
    """测试 API Key 连通性探测接口响应。"""
    # 空 key 测试
    empty_resp = client.post("/api/settings/apikey/test", json={"api_key": ""})
    assert empty_resp.status_code == 200
    assert empty_resp.json()["ok"] is False

    # 非法/伪造 key 测试：应优雅返回失败消息而不是 500
    invalid_resp = client.post(
        "/api/settings/apikey/test",
        json={"api_key": "sk-fake-invalid-key-for-testing", "provider": "dashscope"},
    )
    assert invalid_resp.status_code == 200
    result = invalid_resp.json()
    assert result["ok"] is False
    assert "失败" in result["message"] or "未激活" in result["message"] or "连接" in result["message"]
