"""careercrew_core.tools.mcp - MCP 工具接入。"""
from careercrew_core.tools.mcp.mcp_client import McpClient
from careercrew_core.tools.mcp.mock_apply import (
    HIGH_RISK_TOOLS,
    register_high_risk_tools,
)

__all__ = ["McpClient", "HIGH_RISK_TOOLS", "register_high_risk_tools"]
