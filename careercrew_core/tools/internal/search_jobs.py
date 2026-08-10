"""search_jobs 工具（双平台真实数据）：并行抓取猎聘 + Boss直聘，合并去重。

猎聘：mcp-jobs（Node MCP，Playwright 爬取，1-2 分钟/次）
Boss：boss-cdp-cli.js（CDP 复用登录态，截 joblist.json API 拿明文薪资，几秒/次）
两平台并行抓取，任一失败降级为空（不影响另一个），合并去重后返回 top_k。
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from langchain_core.tools import tool

from careercrew_core.tools.jobs.mcp_jobs import search_jobs_mcp
from careercrew_core.tools.jobs.boss_jobs import search_jobs_boss


def _safe_search(fn, keyword: str, top_k: int) -> list[dict]:
    """安全调用数据源，失败返回空列表（不阻塞聚合）。"""
    try:
        return fn(keyword, top_k=top_k)
    except Exception:
        return []


def _merge_dedup(*sources: list[dict], top_k: int) -> list[dict]:
    """合并多源岗位，按 title+company 去重，截断 top_k。"""
    seen: set[tuple[str, str]] = set()
    merged: list[dict] = []
    for src in sources:
        for j in src:
            title = (j.get("title") or "").strip().lower()
            # 猎聘无 company 字段，用 city 兜底做去重 key
            company = (j.get("company") or j.get("city") or "").strip().lower()
            if not title or (title, company) in seen:
                continue
            seen.add((title, company))
            merged.append(j)
            if len(merged) >= top_k:
                return merged
    return merged


@tool
def search_jobs(direction: str, top_k: int = 8) -> str:
    """按求职方向搜索真实职位 JD（猎聘 + Boss直聘 双平台并行抓取，合并去重）。

    Args:
        direction: 求职方向关键词（如"Java"、"数据分析"、"大模型应用"）。
        top_k: 返回条数。
    """
    # 并行抓取猎聘 + Boss（任一失败降级为空，不影响另一个）
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_liepin = ex.submit(_safe_search, search_jobs_mcp, direction, top_k)
        f_boss = ex.submit(_safe_search, search_jobs_boss, direction, top_k)
        liepin_jobs = f_liepin.result()
        boss_jobs = f_boss.result()

    jobs = _merge_dedup(liepin_jobs, boss_jobs, top_k=top_k)

    if not jobs:
        return json.dumps(
            [{"error": f"未找到与「{direction}」相关的岗位，可换个关键词试试"}],
            ensure_ascii=False,
        )

    # 精简输出字段，给 agent 看关键信息（带来源平台）
    slim = [
        {
            "title": j["title"],
            "city": j.get("city", ""),
            "salary": j.get("salary", ""),
            "experience": j.get("experience", ""),
            "jd": (j.get("raw") or "")[:500],
            "source": j.get("source", ""),
        }
        for j in jobs
    ]
    return json.dumps(slim, ensure_ascii=False)
