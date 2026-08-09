"""search_jobs 工具（真实数据版）：调用 mcp-jobs 实时搜索 Boss直聘/猎聘/拉勾/智联/51job。

替代原 MVP mock 数据。函数签名不变（direction, top_k），agent 无需改动。
mcp-jobs 返回真实岗位（Playwright 爬取，约 1-2 分钟/次）。
"""
from __future__ import annotations

import json

from langchain_core.tools import tool

from careercrew_core.tools.jobs.mcp_jobs import search_jobs_mcp


@tool
def search_jobs(direction: str, top_k: int = 8) -> str:
    """按求职方向搜索真实职位 JD（mcp-jobs 实时抓取 Boss直聘/猎聘/智联等）。

    Args:
        direction: 求职方向关键词（如"Java"、"数据分析"、"大模型应用"）。
        top_k: 返回条数。
    """
    try:
        jobs = search_jobs_mcp(direction, top_k=top_k)
    except Exception as e:
        return json.dumps(
            [{"error": f"暂时无法获取职位（{type(e).__name__}: {e}），请稍后重试"}],
            ensure_ascii=False,
        )

    if not jobs:
        return json.dumps(
            [{"error": f"未找到与「{direction}」相关的岗位，可换个关键词试试"}],
            ensure_ascii=False,
        )

    # 精简输出字段，给 agent 看关键信息
    slim = [
        {
            "title": j["title"],
            "city": j["city"],
            "salary": j["salary"],
            "experience": j["experience"],
            "jd": j["raw"][:500],
        }
        for j in jobs
    ]
    return json.dumps(slim, ensure_ascii=False)
