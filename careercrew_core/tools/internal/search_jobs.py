"""search_jobs 工具：岗位库优先，未命中按 Boss CDP -> 猎聘 MCP 双渠道回退采集。

数据流：库内新鲜命中（默认 7 天窗口）直接返回——重复搜索同一关键词不再触发
1~2 分钟的实时爬取；未命中时优先 Boss直聘渠道（N1：CDP 接管已登录 Chrome，
tools.search.boss_cdp_url 配置后启用），不可用降级 mcp-jobs 猎聘渠道。
两渠道结果均按指纹去重入库（source 区分 boss / liepin）。
"""
from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

from careercrew_core.tools.jobs.mcp_jobs import search_jobs_mcp

logger = logging.getLogger(__name__)

# 库内命中的新鲜度窗口（天）；超过视为过期需重爬
_CACHE_MAX_AGE_DAYS = 7.0


def _slim(jobs: list[dict]) -> list[dict]:
    """精简输出字段，给 agent 看关键信息。"""
    return [
        {
            "title": j.get("title", ""),
            "city": j.get("city", ""),
            "salary": j.get("salary", ""),
            "experience": j.get("experience", ""),
            "jd": (j.get("jd") or j.get("raw") or "")[:500],
        }
        for j in jobs
    ]


def _boss_search(direction: str, top_k: int, boss_cdp_url: str, boss_city: str) -> list[dict]:
    """Boss 渠道薄封装：未配置/不可用时抛异常，由调用方降级。"""
    from careercrew_core.tools.browser.boss_search import search_boss_jobs

    return search_boss_jobs(direction, top_k=top_k, cdp_url=boss_cdp_url, city=boss_city)


def make_search_jobs_tool(jobs_store=None, boss_cdp_url: str = "", boss_city: str = ""):
    """构造 search_jobs 工具。

    jobs_store：启用库缓存；None 保持直连行为。
    boss_cdp_url：非空时启用 Boss直聘 CDP 后端（优先于猎聘 MCP）。
    """

    @tool
    def search_jobs(direction: str, top_k: int = 8) -> str:
        """按求职方向搜索职位 JD（优先本地岗位库，未命中实时抓取 Boss/猎聘平台）。

        Args:
            direction: 求职方向关键词（如"Java"、"数据分析"、"大模型应用"）。
            top_k: 返回条数。
        """
        # 1) 岗位库命中：零子进程直接返回
        if jobs_store is not None:
            try:
                hits = jobs_store.search(direction, top_k=top_k, max_age_days=_CACHE_MAX_AGE_DAYS)
            except Exception:
                hits = []  # 库故障不阻塞查询路径，降级实时爬取
            if hits:
                return json.dumps(_slim(hits), ensure_ascii=False)

        # 2) 未命中：Boss CDP 优先（配置后启用），失败降级猎聘 MCP
        jobs: list[dict] = []
        if boss_cdp_url.strip():
            try:
                jobs = _boss_search(direction, top_k, boss_cdp_url, boss_city)
            except Exception as e:
                logger.warning("Boss 渠道不可用，降级猎聘 MCP：%s: %s", type(e).__name__, e)

        if not jobs:
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

        if jobs_store is not None:
            try:
                jobs_store.upsert(jobs, direction)
            except Exception:
                pass  # 入库失败不影响本次返回

        return json.dumps(_slim(jobs), ensure_ascii=False)

    return search_jobs


@tool
def search_jobs(direction: str, top_k: int = 8) -> str:
    """按求职方向搜索真实职位 JD（mcp-jobs 实时抓取猎聘平台）。

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

    return json.dumps(_slim(jobs), ensure_ascii=False)
