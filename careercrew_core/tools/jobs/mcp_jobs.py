"""猎聘职位搜索接口（向后兼容层）：内部已平滑迁移至 CDP/Patchright 抓取。"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import urljoin

from careercrew_core.tools.browser.liepin_search import search_liepin_jobs
from careercrew_core.tools.jobs.salary_parser import parse_salary_range


def search_jobs_mcp(
    keyword: str, city: str = "", top_k: int = 10, timeout: float = 180.0
) -> list[dict]:
    """向后兼容接口：已切换为 CDP / Patchright 抓取猎聘真实岗位。"""
    # 默认从环境变量或本地默认端口尝试 CDP
    cdp_url = os.environ.get("BOSS_CDP_URL") or "http://127.0.0.1:9222"
    return search_liepin_jobs(keyword, top_k=top_k, cdp_url=cdp_url, city=city)


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
    company = (
        rj.get("company") or rj.get("companyName") or rj.get("company_name") or ""
    ).strip()
    tags = rj.get("tags") if isinstance(rj.get("tags"), list) else []
    experience = next(
        (
            str(tag).strip()
            for tag in tags
            if re.search(r"(?:\d+[-~]?\d*年|经验不限|在校|应届)", str(tag))
        ),
        "",
    )
    detail = (
        rj.get("jobDetail")
        or rj.get("jobUrl")
        or rj.get("job_url")
        or rj.get("url")
        or rj.get("link")
        or ""
    ).strip()
    url = urljoin("https://www.liepin.com", detail)
    raw = " ".join(
        part for part in (title, company, " ".join(map(str, tags))) if part
    )
    return {
        "title": title,
        "company": company,
        "city": (rj.get("address") or rj.get("city") or "").strip(),
        "salary": salary,
        "salary_k": parse_salary_range(salary),
        "experience": experience,
        "raw": raw[:500],
        "url": url,
        "source": "liepin",
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
        # fallback 文本没有可靠字段边界，宁可留空也不把地区/行业猜成公司名
        "company": "",
        "city": city,
        "salary": salary,
        "salary_k": parse_salary_range(salary),
        "experience": exp,
        "raw": content[:300],
        "url": "",
        "source": "liepin",
    }
