"""测试 mcp-jobs 抓取 Boss直聘（zhipin 移动版）岗位。

策略：有头浏览器（headless=false）+ 移动端 UA + 移动端视窗，
绕过 headless 检测 + 避免移动版页面被桌面 UA 重定向。
"""
import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, stdio_client

# 有头 + 移动端 UA + 移动端视窗，提高 m.zhipin.com 成功率
os.environ["CRAWLER_HEADLESS"] = "false"
os.environ["CRAWLER_USER_AGENT"] = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)
os.environ["CRAWLER_VIEWPORT_WIDTH"] = "375"
os.environ["CRAWLER_VIEWPORT_HEIGHT"] = "812"

_ROOT = Path(__file__).resolve().parents[1]
_RUN = _ROOT / "mcp-servers" / "run-mcp-jobs-boss.js"


async def main():
    params = StdioServerParameters(command="node", args=[str(_RUN)], env={**os.environ})
    print(f"启动: node {_RUN.name}")
    print("参数: keyword=Python, headless=false, 移动端UA, 视窗375x812")
    print("（会弹出浏览器窗口，预计 1-2 分钟）\n")

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            resp = await session.call_tool("mcp_search_job", {"keyword": "Python", "page": 1})
            text = "\n".join(
                c.text for c in resp.content if hasattr(c, "text") and c.text
            )

            print("=== 原始返回（前 2000 字）===")
            print(text[:2000])

            try:
                data = json.loads(text)
                jobs = data.get("jobs", [])
                print(f"\n=== 岗位数: {len(jobs)} ===")
                for i, j in enumerate(jobs[:5]):
                    print(f"\n--- 岗位 {i+1} ---")
                    print(json.dumps(j, ensure_ascii=False, indent=2)[:600])
            except json.JSONDecodeError:
                print("\n[返回非 JSON，可能被反爬或需登录]")


if __name__ == "__main__":
    asyncio.run(main())
