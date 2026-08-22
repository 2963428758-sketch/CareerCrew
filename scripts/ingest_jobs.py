"""岗位库增量采集（手动预热）：mcp-jobs 爬取 -> jobs 表按指纹去重入库。

跑法：conda run -n careercrew python scripts/ingest_jobs.py --keyword "大模型应用" [--city 广州] [--top-k 20]
查询路径（search_jobs 工具）只读库；本脚本负责把新鲜岗位灌进库里。
"""
from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keyword", required=True, help="搜索关键词，如「大模型应用」")
    parser.add_argument("--city", default="", help="城市过滤（可空）")
    parser.add_argument("--top-k", type=int, default=20)
    args = parser.parse_args()

    from careercrew_core.jobs import create_jobs_store
    from careercrew_core.state.settings import load_settings
    from careercrew_core.tools.jobs.mcp_jobs import search_jobs_mcp

    settings = load_settings()
    store = create_jobs_store(settings)

    print(f"[jobs] 采集：keyword={args.keyword!r} city={args.city!r} top_k={args.top_k}")
    jobs = search_jobs_mcp(args.keyword, city=args.city, top_k=args.top_k)
    if not jobs:
        print("[jobs] 爬取结果为空")
        return 1

    n = store.upsert(jobs, args.keyword)
    print(f"[jobs] 入库 {n} 条（指纹去重）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
