"""牛客网岗位抓取器：直接 requests 抓取 job/center 页面，解析 __INITIAL_STATE__ 内嵌 JSON。

无需浏览器/Playwright，实时返回真实岗位（校招/实习/社招）。
页面是 React SPA，岗位数据内嵌在 `window.__INITIAL_STATE__`（约 220KB JSON），
路径 `store.interCenter.jobList`，每页 20 条。
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests

# 牛客实习广场（recruitType 在页面内切换，URL 固定）
_JOB_CENTER_URL = "https://www.nowcoder.com/job/center"
# 注意：不要加 Referer 头——牛客会据此返回反爬小页面（无 __INITIAL_STATE__）
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}
_TIMEOUT = 20
_MAX_RETRY = 3
_RETRY_DELAY = 1.5  # 秒，限流/反爬时退避

# recruitType: 1=校招 2=实习 3=社招
RECRUIT_TYPE_NAMES = {1: "校招", 2: "实习", 3: "社招"}


def _extract_initial_state(html: str) -> dict:
    """从 HTML 中提取 __INITIAL_STATE__ JSON（花括号配平）。"""
    idx = html.find("__INITIAL_STATE__=")
    if idx == -1:
        idx = html.find("window.__INITIAL_STATE__=")
    if idx == -1:
        raise RuntimeError("页面未找到 __INITIAL_STATE__")
    brace = html.find("{", idx)
    if brace == -1:
        raise RuntimeError("__INITIAL_STATE__ 无 JSON")
    depth = 0
    i = brace
    while i < len(html):
        ch = html[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    return json.loads(html[brace : i + 1])


def _fetch_page(page: int) -> dict:
    """抓取单页并解析 __INITIAL_STATE__，带重试（限流/反爬退避）。"""
    params = {"page": page} if page > 1 else {}
    last_err: Exception | None = None
    for attempt in range(_MAX_RETRY):
        try:
            resp = requests.get(
                _JOB_CENTER_URL, headers=_HEADERS, params=params, timeout=_TIMEOUT
            )
            resp.raise_for_status()
            html = resp.text
            if "__INITIAL_STATE__" not in html:
                raise RuntimeError("响应无 __INITIAL_STATE__（可能被限流）")
            data = _extract_initial_state(html)
            joblist = data.get("store", {}).get("interCenter", {}).get("jobList")
            if joblist is None:
                raise RuntimeError("响应中无 jobList（可能需要登录）")
            return data
        except Exception as e:  # noqa: BLE001 - 重试兜底
            last_err = e
            time.sleep(_RETRY_DELAY * (attempt + 1))
    raise RuntimeError(f"抓取失败: {last_err}")


def _parse_job(raw: dict) -> dict:
    """把牛客一条岗位解析为统一结构。"""
    d = raw.get("data", raw)
    # 公司名在 user.identity.companyName
    company = ""
    user = d.get("user")
    if isinstance(user, dict):
        ident = user.get("identity")
        if isinstance(ident, dict):
            company = ident.get("companyName") or ""

    # JD：ext.requirements
    jd = ""
    ext = d.get("ext")
    if isinstance(ext, str):
        try:
            jd = json.loads(ext).get("requirements", "") or ""
        except Exception:
            jd = ext
    elif isinstance(ext, dict):
        jd = ext.get("requirements", "") or ""

    salary = d.get("salaryShow") or ""
    if not salary and (d.get("salaryMin") or d.get("salaryMax")):
        salary = f"{d.get('salaryMin', '')}-{d.get('salaryMax', '')}"

    # 技能/方向：从 careerJobName / jobKeys 派生
    skills = []
    if d.get("careerJobName"):
        skills.append(str(d["careerJobName"]))
    jk = d.get("jobKeys")
    if isinstance(jk, list):
        skills.extend(str(k) for k in jk[:5])

    return {
        "company": company or "未知公司",
        "title": d.get("jobName", ""),
        "city": d.get("jobCity", ""),
        "salary": salary,
        "edu": d.get("eduLevel", ""),
        "recruit_type": RECRUIT_TYPE_NAMES.get(d.get("recruitType"), ""),
        "skills": skills,
        "jd": jd,
        "url": f"https://www.nowcoder.com/job/{d.get('id', '')}",
        "source": "nowcoder",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_jobs(
    keyword: str = "",
    city: str = "",
    recruit_type: int | None = None,
    top_k: int = 20,
    max_pages: int = 1,
) -> list[dict]:
    """抓取牛客网岗位并过滤。

    Args:
        keyword: 关键词（匹配标题 + JD，如"Java"、"RAG"）。
        city: 城市（匹配 jobCity，如"广州"）。
        recruit_type: 1校招/2实习/3社招，None=不过滤。
        top_k: 返回条数。
        max_pages: 抓取页数（首页 20 条，多页翻页抓）。
    """
    jobs: list[dict] = []
    for page in range(1, max_pages + 1):
        data = _fetch_page(page)
        joblist = data.get("store", {}).get("interCenter", {}).get("jobList") or []
        for raw in joblist:
            job = _parse_job(raw)
            # 过滤
            if recruit_type is not None and raw.get("data", raw).get("recruitType") != recruit_type:
                continue
            if city and city not in job["city"]:
                continue
            if keyword:
                hay = (job["title"] + " " + job["jd"]).lower()
                if keyword.lower() not in hay:
                    continue
            jobs.append(job)
        if len(joblist) < 20:  # 到底了
            break
        time.sleep(0.8)  # 翻页间隔，避免触发限流
    return jobs[:top_k]
