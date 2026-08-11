"""mcp-jobs MCP 客户端封装：Python 侧调用 mcp-jobs 搜索猎聘真实岗位。

mcp-jobs 是 Node MCP server（Playwright 爬猎聘），
启动方式：node mcp-servers/run-mcp-jobs.js（包装器屏蔽 stdout 日志 + 只启用猎聘）。
每次调用现连现调（spawn 进程 + 浏览器，约 1-2 分钟，返回真实岗位）。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, stdio_client

# mcp-jobs 启动路径（项目内）
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_RUN_SCRIPT = _PROJECT_ROOT / "mcp-servers" / "run-mcp-jobs.js"

_SALARY_K_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*[kK]")
_SALARY_WAN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*万")
_MONTHS_RE = re.compile(r"(\d{1,2})\s*薪")


def _params() -> StdioServerParameters:
    return StdioServerParameters(
        command="node",
        args=[str(_RUN_SCRIPT)],
        env={**os.environ},
    )


def parse_salary_range(text: str) -> dict | None:
    """解析薪资文本为月薪范围（单位 k）与薪数。

    支持 "20-35k" / "40-70k·15薪" / "1.5-2.5万" / "30-60K"；
    "面议" 或无法解析返回 None。
    """
    if not text:
        return None
    t = text.strip()
    if "面议" in t:
        return None
    m = _SALARY_K_RE.search(t)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
    else:
        m = _SALARY_WAN_RE.search(t)
        if not m:
            return None
        lo, hi = float(m.group(1)) * 10, float(m.group(2)) * 10
    months = None
    mm = _MONTHS_RE.search(t)
    if mm:
        months = int(mm.group(1))
    return {"min_k": lo, "max_k": hi, "months": months}


def search_jobs_mcp(
    keyword: str, city: str = "", top_k: int = 10, timeout: float = 180.0
) -> list[dict]:
    """调用 mcp-jobs 搜索真实岗位，返回结构化列表（单次调用 timeout 秒上限）。"""
    result = asyncio.run(asyncio.wait_for(_search(keyword, city, top_k), timeout=timeout))
    return result


async def _search(keyword: str, city: str, top_k: int) -> list[dict]:
    async with stdio_client(_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            # city 恒传（空串兜底）：mcp-jobs 的 searchJobList 会拼
            # keyword + ' ' + city，缺失时 URL 里会出现字面 "undefined"
            args: dict = {"keyword": keyword, "page": 1, "city": city or ""}
            resp = await session.call_tool("mcp_search_job", args)
            text = "\n".join(
                c.text for c in resp.content if hasattr(c, "text") and c.text
            )
            return _parse_response(text, top_k)


def _parse_response(text: str, top_k: int) -> list[dict]:
    """解析 mcp-jobs 返回的 JSON（{"jobs":[{...}]}）为结构化岗位。

    优先结构化字段（title/salary/company），缺失时回退 content 文本解析。
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    raw_jobs = data.get("jobs") or []
    jobs: list[dict] = []
    for rj in raw_jobs:
        if not isinstance(rj, dict):
            continue
        if rj.get("title") or rj.get("salary"):
            jobs.append(_parse_structured(rj))
            continue
        content = rj.get("content") or rj.get("text") or ""
        if not content:
            continue
        jobs.append(_parse_content(content))
    return jobs[:top_k]


def _parse_structured(rj: dict) -> dict:
    """结构化 job 字段（title/salary/company/address）直接取用。"""
    title = (rj.get("title") or "").strip()
    salary = (rj.get("salary") or "").strip()
    return {
        "title": title,
        "city": (rj.get("address") or rj.get("city") or "").strip(),
        "salary": salary,
        "salary_k": parse_salary_range(salary),
        "experience": "",
        "raw": title[:300],
        "source": "mcp-jobs",
    }


def _parse_content(content: str) -> dict:
    """把 mcp-jobs 的 content 字符串解析为字段（标题/城市/薪资/经验等）。"""
    # 格式示例："Java开发【广州-海珠区】14-18k 4-10年 统招本科 某公司 ..."
    title = content
    city = ""
    salary = ""
    exp = ""

    # 城市【...】
    m = re.search(r"【([^】]*)】", content)
    if m:
        city = m.group(1).replace("广州-", "").strip()
        title = content[: m.start()].strip()

    # 薪资 数字-数字k（可带 ·15薪 等薪数）
    m = re.search(
        r"(\d+(?:\.\d+)?\s*[-~]\s*\d+(?:\.\d+)?)\s*[kK](?:·\d{1,2}薪)?",
        content,
        re.IGNORECASE,
    )
    if m:
        salary = m.group(0).upper()
    else:
        m = re.search(r"(\d+(?:\.\d+)?\s*[-~]\s*\d+(?:\.\d+)?)\s*万", content)
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
        "salary_k": parse_salary_range(salary),
        "experience": exp,
        "raw": content[:300],
        "source": "mcp-jobs",
    }
