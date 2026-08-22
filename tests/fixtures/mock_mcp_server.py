"""Mock MCP server（E2 测试用）：low-level stdio server，暴露 search_jobs_mcp 工具。"""
from __future__ import annotations

import asyncio
import json

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

app = Server("mock-jobs")


@app.list_tools()
async def list_tools() -> ListToolsResult:
    return ListToolsResult(tools=[
        Tool(
            name="search_jobs_mcp",
            description="mock 职位搜索（MCP 测试）",
            inputSchema={
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "description": "求职方向"},
                    "top_k": {"type": "integer", "description": "返回条数"},
                },
                "required": ["direction"],
            },
        )
    ])


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> CallToolResult:
    if name == "search_jobs_mcp":
        args = arguments or {}
        top_k = args.get("top_k") or 5
        data = [
            {"company": "TestCorp", "title": "大模型应用工程师", "skills": ["Python", "RAG"], "score": 0.9},
            {"company": "TestCorp2", "title": "Java 后端开发", "skills": ["Java"], "score": 0.5},
        ][:top_k]
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(data, ensure_ascii=False))])
    raise ValueError(f"Unknown tool: {name}")
async def main() -> None:
    async with stdio_server() as (read, write):
        await app.run(read, write, initialization_options=app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
