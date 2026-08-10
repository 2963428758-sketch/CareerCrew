"""mcp-jobs MCP 客户端封装：Python 侧调用 mcp-jobs 搜索猎聘真实岗位。

mcp-jobs 是 Node MCP server（Playwright 爬猎聘），
启动方式：node mcp-servers/run-mcp-jobs.js（包装器屏蔽 stdout 日志 + 只启用猎聘）。
每次调用现连现调（spawn 进程 + 浏览器，约 1-2 分钟，返回真实岗位）。
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, stdio_client

# mcp-jobs 启动路径（项目内）
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_RUN_SCRIPT = _PROJECT_ROOT / "mcp-servers" / "run-mcp-jobs.js"


def _params() -> StdioServerParameters:
    return StdioServerParameters(
        command="node",
        args=[str(_RUN_SCRIPT)],
        env={**os.environ},
    )


def search_jobs_mcp(keyword: str, city: str = "", top_k: int = 10) -> list[dict]:
    """调用 mcp-jobs 搜索真实岗位，返回结构化列表。"""
    result = asyncio.run(_search(keyword, city, top_k))
    return result


async def _search(keyword: str, city: str, top_k: int) -> list[dict]:
    async with stdio_client(_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            args: dict = {"keyword": keyword, "page": 1}
            if city:
                args["city"] = city
            resp = await session.call_tool("mcp_search_job", args)
            text = "\n".join(
                c.text for c in resp.content if hasattr(c, "text") and c.text
            )
            return _parse_response(text, top_k)


def _parse_response(text: str, top_k: int) -> list[dict]:
    """解析 mcp-jobs 返回的 JSON（{"jobs":[{content: "..."}]}）为结构化岗位。"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    raw_jobs = data.get("jobs") or []
    jobs: list[dict] = []
    for rj in raw_jobs:
        content = rj.get("content") or rj.get("text") or ""
        if not content:
            continue
        jobs.append(_parse_content(content))
    return jobs[:top_k]


def _parse_content(content: str) -> dict:
    """把 mcp-jobs 的 content 字符串解析为字段（标题/城市/薪资/经验等）。"""
    # 格式示例："Java开发【广州-海珠区】14-18k 4-10年 统招本科 某公司 ..."
    import re

    title = content
    city = ""
    salary = ""
    exp = ""

    # 城市【...】
    m = re.search(r"【([^】]*)】", content)
    if m:
        city = m.group(1).replace("广州-", "").strip()
        title = content[: m.start()].strip()

    # 薪资 数字-数字k
    m = re.search(r"(\d+[.-]\d+)\s*k", content, re.IGNORECASE)
    if m:
        salary = m.group(0).upper()
    else:
        m = re.search(r"(\d+-\d+万)", content)
        if m:
            salary = m.group(1)

    # 经验
    m = re.search(r"((?:\d+[-~]\d+|\d+)年)", content)
    if m:
        exp = m.group(1)

    return {
        "title": title,
        "city": city,
        "salary": salary,
        "experience": exp,
        "raw": content[:300],
        "source": "mcp-jobs",
    }
