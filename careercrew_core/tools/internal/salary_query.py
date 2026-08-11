"""salary_query 工具：猎聘实时 JD 薪资查询（真实数据 + 聚合）。

复用 mcp-jobs（Playwright 爬猎聘）查真实岗位薪资，按「公司 + 岗位方向」搜索，
噪音过滤后聚合成方向级月薪区间/中位数与样本，供谈判师/规划师引用。
每次 agent 会话（new_consult_agent）最多调用 max_calls 次（默认 2）。
"""
from __future__ import annotations

import json
import re
import statistics

from langchain_core.tools import tool

from careercrew_core.tools.jobs.mcp_jobs import search_jobs_mcp

_DEFAULT_MAX_CALLS = 2
_TIMEOUT_S = 180.0
_SAMPLE_LIMIT = 5

_GENERIC_ROLE_SUFFIXES = (
    "工程师", "专家", "研究员", "分析师", "架构师", "设计师", "顾问",
    "经理", "总监", "主管", "开发", "研发", "算法", "运维", "测试",
    "运营", "产品", "销售", "岗", "岗位",
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def _title_matches(title: str, direction: str) -> bool:
    if not direction:
        return True
    t = _norm(title)
    tokens = [x for x in (_norm(p) for p in re.split(r"[\s/、,，]+", direction)) if x]
    if len(tokens) > 1:
        return all(tok in t for tok in tokens)
    d = tokens[0]
    if d in t:
        return True
    # 复合方向（如"大模型工程师"）去掉通用岗位后缀后按词头匹配，
    # 兼容"大模型算法工程师"等真实标题
    for suffix in _GENERIC_ROLE_SUFFIXES:
        if d.endswith(suffix) and len(d) > len(suffix) + 1:
            head = d[: -len(suffix)]
            if head in t:
                return True
    return False


def _city_matches(city: str, title: str, requested: str) -> bool:
    if not requested:
        return True
    return _norm(requested) in _norm(city) or _norm(requested) in _norm(title)


def aggregate_salaries(jobs: list[dict]) -> dict:
    """聚合可解析薪资的岗位：样本数、月薪 min/max/中位、带薪数年薪区间。"""
    parsed = [
        j for j in jobs
        if (j.get("salary_k") or {}).get("min_k") is not None
    ]
    total = len(jobs)
    if not parsed:
        return {"sample_count": 0, "total_count": total}
    mins = [s["salary_k"]["min_k"] for s in parsed]
    maxs = [s["salary_k"]["max_k"] for s in parsed]
    midpoints = [(a + b) / 2 for a, b in zip(mins, maxs)]
    with_months = [s for s in parsed if s["salary_k"].get("months")]
    annual = None
    if with_months:
        annual = {
            "min": round(
                min(s["salary_k"]["min_k"] * s["salary_k"]["months"] for s in with_months), 1
            ),
            "max": round(
                max(s["salary_k"]["max_k"] * s["salary_k"]["months"] for s in with_months), 1
            ),
            "samples": len(with_months),
        }
    return {
        "sample_count": len(parsed),
        "total_count": total,
        "monthly_k": {
            "min": round(min(mins), 1),
            "max": round(max(maxs), 1),
            "median": round(statistics.median(midpoints), 1),
        },
        "annual_k": annual,
    }


def make_salary_query_tool(max_calls: int = _DEFAULT_MAX_CALLS):
    """构造 salary_query 工具；每次 agent 实例独立计数，超限返回可读提示。"""
    calls = 0

    @tool
    def salary_query(direction: str, city: str = "", company: str = "", top_k: int = 8) -> str:
        """查询猎聘实时 JD 的真实薪资，返回聚合月薪区间与关键样本。

        Args:
            direction: 岗位方向关键词（如"大模型工程师"、"Java 后端"）。
            city: 城市（如"北京"），可选。
            company: 目标公司关键词（如"字节跳动"），可选，会与 direction 组合搜索。
            top_k: 聚合使用的样本条数。
        """
        nonlocal calls
        if calls >= max_calls:
            return json.dumps(
                {
                    "error": (
                        f"已达到本会话 salary_query 调用上限（{max_calls} 次），"
                        "请基于已有数据作答"
                    )
                },
                ensure_ascii=False,
            )
        calls += 1
        keyword = f"{company} {direction}".strip()
        try:
            jobs = search_jobs_mcp(keyword, city, top_k=top_k, timeout=_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001 - 工具层兜底，不中断 agent
            return json.dumps(
                {
                    "error": (
                        f"薪资查询暂时不可用（{type(e).__name__}: {e}），"
                        "请基于常识给出估算并标注"
                    )
                },
                ensure_ascii=False,
            )

        # 噪音过滤：标题必须含 direction；指定城市时结果需含城市
        jobs = [j for j in jobs if _title_matches(j.get("title", ""), direction)]
        if city:
            jobs = [
                j for j in jobs
                if _city_matches(j.get("city", ""), j.get("title", ""), city)
            ]

        agg = aggregate_salaries(jobs)
        if agg["sample_count"] == 0:
            return json.dumps(
                {
                    "error": (
                        f"未找到「{direction}」相关岗位的有效薪资数据，"
                        "可换关键词/公司/城市再试，或基于常识给出估算"
                    )
                },
                ensure_ascii=False,
            )

        samples = [
            {
                "title": j.get("title", ""),
                "company": j.get("company", ""),
                "salary": j.get("salary", ""),
                "city": j.get("city", ""),
                "experience": j.get("experience", ""),
            }
            for j in jobs[:_SAMPLE_LIMIT]
        ]
        return json.dumps(
            {
                "query": {"direction": direction, "city": city, "company": company},
                "source": "liepin(猎聘实时JD)",
                **agg,
                "samples": samples,
            },
            ensure_ascii=False,
        )

    return salary_query
