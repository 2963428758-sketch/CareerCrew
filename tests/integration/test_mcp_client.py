"""E2 MCP client 测试：Mock MCP server 发现 + 注册 + 执行。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from mcp.client.stdio import StdioServerParameters

from careercrew_core.tools.mcp.mcp_client import McpClient
from careercrew_core.tools.registry import ToolRegistry

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mock_mcp_server.py"
TOOL_NAME = "mcp_jobs_search_jobs_mcp"


@pytest.mark.integration
def test_mcp_client_discovers_registers_executes() -> None:
    params = StdioServerParameters(command=sys.executable, args=[str(FIXTURES)])
    client = McpClient(params, prefix="mcp_jobs")
    reg = ToolRegistry()
    names = client.discover_and_register(reg)
    assert TOOL_NAME in names
    assert reg.has(TOOL_NAME)
    out = reg.execute(TOOL_NAME, direction="大模型", top_k=2)
    assert "TestCorp" in out
