"""Boss直聘 CDP 抓取封装：subprocess 调 boss-cdp-cli.js，解析 JSON。

前置：Chrome 以 --remote-debugging-port=9222 启动且已登录 boss直聘
（登录态持久保存在 --user-data-dir 指向的 profile，重启不丢）。
未启动时返回空列表（不阻塞，猎聘等其他数据源正常工作）。

方案：CDP 复用真实登录态 + 截 wapi/zpgeek/search/joblist.json 拿明文薪资，
绕过字体反爬与登录墙。详见 scripts/boss_cdp_jobs.js（验证原型）。
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CLI_SCRIPT = _PROJECT_ROOT / "mcp-servers" / "boss-cdp-cli.js"
_NODE = os.environ.get("NODE", "node")
# Chrome CDP 端口（Chrome 须以 --remote-debugging-port=9222 启动并登录 boss直聘）
_CDP_URL = os.environ.get("BOSS_CDP_URL", "http://localhost:9222")

# Boss 城市名 -> 城市代码（PC 版搜索用，与 m.zhipin.com 同体系）
_CITY_CODES = {
    "北京": "101010100", "上海": "101020100", "广州": "101280100",
    "深圳": "101280600", "杭州": "101210100", "成都": "101270100",
    "南京": "101190100", "武汉": "101200100", "西安": "101110100",
    "苏州": "101190400", "天津": "101030100", "重庆": "101040100",
    "长沙": "101250100", "郑州": "101180100", "东莞": "101281600",
    "青岛": "101120200", "合肥": "101220100", "佛山": "101280800",
    "宁波": "101210400", "厦门": "101230200", "大连": "101070200",
    "福州": "101230100", "济南": "101120100", "珠海": "101280700",
    "无锡": "101190200", "昆明": "101290100", "哈尔滨": "101050100",
    "沈阳": "101070100", "长春": "101060100", "石家庄": "101090100",
}


def search_jobs_boss(keyword: str, city: str = "", top_k: int = 10) -> list[dict]:
    """调 boss-cdp-cli.js 抓取 Boss直聘岗位，返回结构化列表。

    Args:
        keyword: 搜索关键词
        city: 城市名（如"广州"）；空则全国
        top_k: 返回条数

    Returns:
        [{title, city, salary, experience, raw, source, company, tags, ...}]
        CDP 未连接/未登录时返回 []（不抛异常，不阻塞聚合层）
    """
    city_code = _CITY_CODES.get(city, "")
    args = [_NODE, str(_CLI_SCRIPT), "--keyword", keyword, "--top", str(top_k)]
    if city_code:
        args += ["--city", city_code]

    # 重试 3 次（connectOverCDP + newPage 导航偶发 about:blank，重试提高成功率）
    for _attempt in range(3):
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=90,
                cwd=str(_PROJECT_ROOT),
                env={**os.environ, "BOSS_CDP_URL": _CDP_URL},
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return []
        jobs = _parse(proc.stdout, top_k)
        if jobs:
            return jobs
    return []


def _parse(stdout: str, top_k: int) -> list[dict]:
    """解析 boss-cdp-cli.js stdout 的 JSON，返回统一结构。"""
    stripped = stdout.strip()
    if not stripped:
        return []
    # stdout 最后一行是 JSON（前面可能有 console.error 的诊断）
    line = stripped.splitlines()[-1]
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return []
    if data.get("error"):
        return []  # CDP 未连接 / 未登录等，降级返回空
    jobs: list[dict] = []
    for j in data.get("jobs", [])[:top_k]:
        jobs.append({
            "title": j.get("title", ""),
            "city": j.get("city", ""),
            "salary": j.get("salary", ""),
            "experience": j.get("experience", ""),
            "raw": j.get("raw", ""),
            "source": "boss",
            # Boss 额外字段（猎聘无，聚合时兼容）
            "company": j.get("company", ""),
            "tags": j.get("tags", []),
            "welfare": j.get("welfare", []),
            "industry": j.get("industry", ""),
            "scale": j.get("scale", ""),
            "education": j.get("education", ""),
            "url": j.get("url", ""),
        })
    return jobs
