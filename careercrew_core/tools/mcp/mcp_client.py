"""MCP 工具发现与注册（E2）。

通过 stdio 连接 MCP server（mcp-jobs / Google MCP），list_tools 发现工具，
包装成 langchain StructuredTool（args schema 从 MCP inputSchema 转 pydantic），
注册进 ToolRegistry（source="mcp"）。

MVP 真实 mcp-jobs 未配置时用 search_jobs mock 兜底（N 阶段接真实投递）。
每次工具调用现连现调（低频可接受，避免持久会话的 async 生命周期复杂度）。
"""
from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from pydantic import Field, create_model

from careercrew_core.tools.registry import ToolRegistry, ToolSpec


class McpClient:
    """连接 MCP server 并注册其工具到 ToolRegistry。"""

    def __init__(self, server_params: StdioServerParameters, prefix: str = "mcp") -> None:
        self._server_params = server_params
        self._prefix = prefix

    def discover_and_register(self, registry: ToolRegistry) -> list[str]:
        """发现并注册 MCP server 的工具，返回注册的工具名。"""
        return asyncio.run(self._discover(registry))

    async def _discover(self, registry: ToolRegistry) -> list[str]:
        async with stdio_client(self._server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                registered: list[str] = []
                for t in tools.tools:
                    name = f"{self._prefix}_{t.name}"
                    registry.register(
                        ToolSpec(tool=self._wrap_tool(name, t), source="mcp")
                    )
                    registered.append(name)
                return registered

    def _wrap_tool(self, name: str, mcp_tool) -> BaseTool:
        """包装 MCP 工具为 langchain StructuredTool：调用时现连现调。"""
        params = self._server_params
        tool_name = mcp_tool.name

        async def _acall(**kwargs: Any) -> str:
            async with stdio_client(params) as (r, w):
                async with ClientSession(r, w) as sess:
                    await sess.initialize()
                    result = await sess.call_tool(tool_name, kwargs)
                    return "\n".join(
                        c.text for c in result.content if hasattr(c, "text")
                    )

        def _call(**kwargs: Any) -> str:
            return asyncio.run(_acall(**kwargs))

        return StructuredTool.from_function(
            func=_call,
            name=name,
            description=mcp_tool.description or mcp_tool.name,
            args_schema=_schema_to_model(name, mcp_tool.input_schema),
        )


def _schema_to_model(name: str, json_schema: dict | None):
    """MCP tool inputSchema（JSON Schema）-> pydantic model（支持基本类型）。"""
    props = (json_schema or {}).get("properties", {})
    required = set((json_schema or {}).get("required", []))
    type_map = {
        "string": str, "integer": int, "number": float, "boolean": bool, "array": list,
    }
    fields: dict[str, tuple[Any, Any]] = {}
    for pname, pdesc in props.items():
        t = type_map.get(pdesc.get("type", "string"), str)
        default = (
            Field(..., description=pdesc.get("description", ""))
            if pname in required
            else Field(None, description=pdesc.get("description", ""))
        )
        fields[pname] = (t, default)
    return create_model(name, **fields)
