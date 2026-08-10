"""MCP server 工具注册测试（不触发重型初始化）。"""
from __future__ import annotations

import asyncio


def test_mcp_four_tools_registered() -> None:
    from careercrew_mcp.server import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert {"ingest_document", "search", "query", "status"} <= names
