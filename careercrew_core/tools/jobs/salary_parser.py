"""薪资解析通用工具函数。

支持 "20-35k" / "40-70k·15薪" / "1.5-2.5万" / "30-60K" 等月薪区间与薪数解析。
"""
from __future__ import annotations

import re

_SALARY_K_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*[kK]")
_SALARY_WAN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-~]\s*(\d+(?:\.\d+)?)\s*万")
_MONTHS_RE = re.compile(r"(\d{1,2})\s*薪")


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
