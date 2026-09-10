from __future__ import annotations


def test_tool_operations_api_admin_lifecycle(client, fake_runtime):
    response = client.get("/api/tools", params={"module": "chat"})
    assert response.status_code == 200, response.text
    tool = next(item for item in response.json()["tools"] if item["id"] == "rag_query")
    assert tool["enabled"] is True
    assert "health" in tool

    updated = client.put("/api/tools/rag_query", json={"enabled": False, "reason": "维护"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["enabled"] is False
    calls = client.get("/api/tools/calls")
    assert calls.status_code == 200
    audit = client.get("/api/tools/audit")
    assert audit.status_code == 200
    assert audit.json()[0]["tool_id"] == "rag_query"


def test_tool_operations_api_rejects_unknown_tool(client):
    response = client.put("/api/tools/not-registered", json={"enabled": False})
    assert response.status_code == 400


def test_tool_operations_api_maps_policy_store_outage_to_503(client, fake_runtime):
    class BrokenPolicyStore:
        def status(self, _module):
            raise TimeoutError("postgres unavailable")

    fake_runtime.tool_operations_center = BrokenPolicyStore()
    response = client.get("/api/tools", params={"module": "chat"})

    assert response.status_code == 503
    assert response.json()["detail"] == "工具中心暂时不可用"
