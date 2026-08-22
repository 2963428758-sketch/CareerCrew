"""search_jobs 工具：岗位库优先，未命中才回退 mcp-jobs 实时爬取。

数据流：库内新鲜命中（默认 7 天窗口）直接返回——重复搜索同一关键词不再触发
1~2 分钟的子进程爬取；未命中时爬取一批并按指纹去重入库后返回。
采集器也可独立跑 scripts/ingest_jobs.py 预热岗位库。
"""
from __future__ import annotations

import json

from langchain_core.tools import tool

from careercrew_core.tools.jobs.mcp_jobs import search_jobs_mcp

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


def make_search_jobs_tool(jobs_store=None):
    """构造 search_jobs 工具；传入 JobsStore 启用库缓存，None 时保持直连 MCP 行为。"""

    @tool
    def search_jobs(direction: str, top_k: int = 8) -> str:
        """按求职方向搜索职位 JD（优先本地岗位库，未命中才实时抓取猎聘平台）。

        Args:
            direction: 求职方向关键词（如"Java"、"数据分析"、"大模型应用"）。
            top_k: 返回条数。
        """
        # 1) 岗位库命中：零子进程直接返回
        if jobs_store is not None:
            try:
                hits = jobs_store.search(direction, top_k=top_k, max_age_days=_CACHE_MAX_AGE_DAYS)
            except Exception:
                hits = []  # 库故障不阻塞查询路径，降级直连爬取
            if hits:
                return json.dumps(_slim(hits), ensure_ascii=False)

        # 2) 未命中：实时爬取并入库
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
