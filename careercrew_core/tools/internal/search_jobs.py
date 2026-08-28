"""search_jobs 工具：岗位库优先，未命中同时汇总 Boss 与猎聘双渠道。

数据流：库内新鲜命中（默认 7 天窗口）直接返回——重复搜索同一关键词不再触发
1~2 分钟的实时爬取；未命中时从已配置的 Boss直聘渠道（CDP 接管已登录 Chrome）
和 mcp-jobs 猎聘渠道分别采集，再交错合并，避免单一平台结果占满列表。
两渠道结果均按指纹去重入库（source 区分 boss / liepin）。
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain_core.tools import tool

from careercrew_core.jobs.store import parse_job_search_query, rank_job_matches
from careercrew_core.tools.browser.liepin_search import search_liepin_jobs
from careercrew_core.tools.jobs.mcp_jobs import search_jobs_mcp

logger = logging.getLogger(__name__)

# 库内命中的新鲜度窗口（天）；超过视为过期需重爬
_CACHE_MAX_AGE_DAYS = 7.0
# 首次实时检索不能让单个慢平台把整轮回答拖到 1~2 分钟。
_LIEPIN_TIMEOUT_SECONDS = 25.0

_REALTIME_KEYWORDS = ("实时", "重新", "刷新", "最新", "重搜", "再搜", "抓取", "爬取")

_INTENT_PREFIXES = (
    "帮我实时抓取一下",
    "实时抓取一下",
    "帮我实时抓取",
    "实时抓取",
    "实时检索",
    "实时搜索",
    "重新抓取",
    "重新搜索",
    "重新检索",
    "帮我重新",
    "帮我抓取",
    "帮我找",
    "我要找",
    "我想找",
    "想找",
    "实时",
    "重新",
    "刷新",
    "最新",
    "爬取",
    "抓取",
)


def _detect_realtime_intent(direction: str, realtime: bool = False) -> bool:
    """判断是否需要穿透本地缓存进行实时抓取。"""
    if realtime:
        return True
    return any(kw in direction for kw in _REALTIME_KEYWORDS)


def _clean_direction_query(direction: str) -> str:
    """清理搜索词中的过程性/实时动词，提取核心搜索词。"""
    cleaned = direction
    for p in _INTENT_PREFIXES:
        cleaned = cleaned.replace(p, " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or direction.strip()


def _slim(jobs: list[dict], retrieval_mode: str) -> list[dict]:
    """精简输出字段，给 agent 看关键信息。"""
    result = []
    for j in jobs:
        source = str(j.get("source") or "").strip().lower()
        normalized_source = "liepin" if source in {"liepin", "mcp-jobs"} else source
        source_label = {
            "boss": "Boss直聘",
            "liepin": "猎聘",
        }.get(normalized_source, "来源未标注")
        result.append({
            "company": j.get("company") or "公司名称未提供",
            "title": j.get("title", ""),
            "city": j.get("city", ""),
            "salary": j.get("salary", ""),
            "experience": j.get("experience", ""),
            "source": normalized_source or "unknown",
            "source_label": source_label,
            "retrieval_mode": retrieval_mode,
            "retrieval_mode_label": "近期缓存" if retrieval_mode == "cache" else "实时检索",
            "matched_core_terms": j.get("matched_core_terms", []),
            "matched_location_terms": j.get("matched_location_terms", []),
            "url": j.get("url", ""),
            "jd": (j.get("jd") or j.get("raw") or "")[:500],
        })
    return result


def _merge_channels(channel_jobs: list[list[dict]], top_k: int) -> list[dict]:
    """按渠道交错合并并去重，保证两个来源都有机会出现在有限结果中。"""
    queues = [list(jobs) for jobs in channel_jobs if jobs]
    merged: list[dict] = []
    seen: set[tuple[str, ...]] = set()
    while queues and len(merged) < top_k:
        active: list[list[dict]] = []
        for queue in queues:
            if not queue:
                continue
            job = queue.pop(0)
            source = str(job.get("source") or "").strip().lower()
            source = "liepin" if source in {"liepin", "mcp-jobs"} else source
            url = str(job.get("url") or "").strip().lower()
            identity = (
                source,
                url,
            ) if url else (
                source,
                str(job.get("title") or "").strip().lower(),
                str(job.get("company") or "").strip().lower(),
                str(job.get("city") or "").strip().lower(),
            )
            if identity not in seen:
                seen.add(identity)
                merged.append(job)
            if queue:
                active.append(queue)
            if len(merged) >= top_k:
                break
        queues = active
    return merged


_orig_search_liepin_jobs = search_liepin_jobs
_orig_search_jobs_mcp = search_jobs_mcp


def _boss_search(direction: str, top_k: int, boss_cdp_url: str, boss_city: str) -> list[dict]:
    """Boss 渠道薄封装：未配置/不可用时抛异常，由调用方降级。"""
    from careercrew_core.tools.browser.boss_search import search_boss_jobs

    return search_boss_jobs(direction, top_k=top_k, cdp_url=boss_cdp_url, city=boss_city)


def _liepin_search(direction: str, top_k: int, cdp_url: str, city: str) -> list[dict]:
    """猎聘 渠道薄封装：CDP 抓取；未配置/不可用时抛异常。"""
    if search_liepin_jobs is not _orig_search_liepin_jobs:
        try:
            return search_liepin_jobs(direction, top_k=top_k, cdp_url=cdp_url, city=city)
        except TypeError:
            return search_liepin_jobs(direction, top_k=top_k)
    if search_jobs_mcp is not _orig_search_jobs_mcp:
        try:
            return search_jobs_mcp(direction, top_k=top_k, timeout=_LIEPIN_TIMEOUT_SECONDS)
        except TypeError:
            return search_jobs_mcp(direction, top_k=top_k)
    return search_liepin_jobs(direction, top_k=top_k, cdp_url=cdp_url, city=city)



def make_search_jobs_tool(jobs_store=None, boss_cdp_url: str = "", boss_city: str = ""):
    """构造 search_jobs 工具。

    jobs_store：启用库缓存；None 保持直连行为。
    boss_cdp_url：非空时启用 Boss直聘 与 猎聘 CDP 后端并交错合并。
    """

    @tool
    def search_jobs(direction: str, top_k: int = 8, realtime: bool = False) -> str:
        """按求职方向搜索职位 JD（优先本地岗位库，用户要求实时或未命中时抓取 Boss/猎聘平台）。

        Args:
            direction: 求职方向关键词（如"Java"、"大模型应用实习 广州"）。
            top_k: 返回条数（默认 8）。
            realtime: 是否强制实时抓取（当用户要求“实时抓取/刷新/最新岗位”时设为 True，跳过本地缓存）。
        """
        force_realtime = _detect_realtime_intent(direction, realtime=realtime)
        search_query_str = _clean_direction_query(direction) if force_realtime else direction
        query = parse_job_search_query(search_query_str)

        # 1) 岗位库命中：非强制实时且存在新鲜缓存时直接返回
        if not force_realtime and jobs_store is not None:
            try:
                hits = jobs_store.search(search_query_str, top_k=top_k, max_age_days=_CACHE_MAX_AGE_DAYS)
            except Exception:
                hits = []  # 库故障不阻塞查询路径，降级实时爬取
            if hits:
                return json.dumps(_slim(hits, "cache"), ensure_ascii=False)

        # 2) 实时抓取：推断有效城市
        effective_city = boss_city.strip()
        if not effective_city and query.location_terms:
            effective_city = query.location_terms[0]

        channel_results: dict[str, list[dict]] = {}
        errors: list[str] = []
        tasks = {}
        cdp_url = boss_cdp_url.strip()
        fetch_limit = max(top_k * 3, 25)
        if cdp_url:
            tasks["Boss直聘"] = lambda: _boss_search(
                search_query_str, fetch_limit, cdp_url, effective_city
            )
            tasks["猎聘"] = lambda: _liepin_search(
                search_query_str, fetch_limit, cdp_url, effective_city
            )
        else:
            # 兼容：允许通过模块属性覆盖或测试桩模拟猎聘
            tasks["猎聘"] = lambda: _liepin_search(
                search_query_str, fetch_limit, cdp_url, effective_city
            )

        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            futures = {executor.submit(fetch): label for label, fetch in tasks.items()}
            for future in as_completed(futures):
                label = futures[future]
                try:
                    found = future.result()
                except Exception as e:
                    errors.append(label)
                    logger.warning("%s 渠道不可用：%s: %s", label, type(e).__name__, e)
                    continue
                if found:
                    relevant = rank_job_matches(found, query, fetch_limit)
                    if relevant:
                        channel_results[label] = relevant

        jobs = _merge_channels(
            [channel_results[label] for label in tasks if label in channel_results],
            top_k,
        )

        if not jobs:
            # 优雅降级：如果用户要求实时抓取但实时未获取到新结果，回退本地库缓存
            if force_realtime and jobs_store is not None:
                try:
                    fallback_hits = jobs_store.search(search_query_str, top_k=top_k, max_age_days=_CACHE_MAX_AGE_DAYS)
                    if fallback_hits:
                        logger.info("实时抓取未获得新岗位，降级返回本地缓存 %d 条", len(fallback_hits))
                        return json.dumps(_slim(fallback_hits, "cache"), ensure_ascii=False)
                except Exception:
                    pass

            if errors and len(errors) == len(tasks):
                return json.dumps(
                    [{"error": "Boss直聘/猎聘暂时无法获取职位，请确认 Chrome 调试窗口已开启并已登录"}],
                    ensure_ascii=False,
                )
            return json.dumps(
                [{"error": f"未找到与「{direction}」相关的岗位，可换个关键词试试"}],
                ensure_ascii=False,
            )

        if jobs_store is not None:
            try:
                jobs_store.upsert(jobs, search_query_str)
            except Exception:
                pass  # 入库失败不影响本次返回

        return json.dumps(_slim(jobs, "live"), ensure_ascii=False)

    return search_jobs


@tool
def search_jobs(direction: str, top_k: int = 8, realtime: bool = False) -> str:
    """按求职方向搜索真实职位 JD（默认使用猎聘平台）。

    Args:
        direction: 求职方向关键词（如"Java"、"数据分析"、"大模型应用"）。
        top_k: 返回条数。
        realtime: 是否强制实时抓取。
    """
    clean_query = _clean_direction_query(direction) if _detect_realtime_intent(direction, realtime) else direction
    try:
        jobs = search_jobs_mcp(clean_query, top_k=top_k)
    except Exception as e:
        return json.dumps(
            [{"error": f"暂时无法获取职位（{type(e).__name__}: {e}），请稍后重试"}],
            ensure_ascii=False,
        )

    jobs = rank_job_matches(jobs, parse_job_search_query(clean_query), top_k)
    if not jobs:
        return json.dumps(
            [{"error": f"未找到与「{direction}」相关的岗位，可换个关键词试试"}],
            ensure_ascii=False,
        )

    return json.dumps(_slim(jobs, "live"), ensure_ascii=False)

