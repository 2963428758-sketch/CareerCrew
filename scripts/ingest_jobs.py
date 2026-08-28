"""岗位库增量采集（手动预热）：CDP 爬取 Boss/猎聘 -> jobs 表按指纹去重入库。

跑法：conda run -n careercrew python scripts/ingest_jobs.py --keyword "大模型应用" [--city 广州] [--platform both|boss|liepin] [--top-k 20]
查询路径（search_jobs 工具）优先读库；本脚本负责把新鲜岗位灌进库里。
"""
from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keyword", required=True, help="搜索关键词，如「大模型应用」")
    parser.add_argument("--city", default="", help="城市过滤（如「广州」）")
    parser.add_argument("--platform", choices=["both", "boss", "liepin"], default="both", help="采集平台")
    parser.add_argument("--top-k", type=int, default=20)
    args = parser.parse_args()

    from careercrew_core.jobs import create_jobs_store
    from careercrew_core.state.settings import load_settings
    from careercrew_core.tools.browser.boss_search import search_boss_jobs
    from careercrew_core.tools.browser.liepin_search import search_liepin_jobs

    settings = load_settings()
    store = create_jobs_store(settings)
    boss_cfg = getattr(settings.tools, "search", None)
    cdp_url = (getattr(boss_cfg, "boss_cdp_url", "") or "http://127.0.0.1:9222").strip()

    print(f"[jobs] 采集：keyword={args.keyword!r} city={args.city!r} platform={args.platform} top_k={args.top_k}")
    jobs: list[dict] = []
    if args.platform in ("both", "boss"):
        try:
            print("[jobs] 正在从 Boss直聘 (CDP) 采集...")
            boss_jobs = search_boss_jobs(args.keyword, top_k=args.top_k, cdp_url=cdp_url, city=args.city)
            jobs.extend(boss_jobs)
            print(f"[jobs] Boss直聘采集到 {len(boss_jobs)} 条")
        except Exception as e:
            print(f"[jobs] Boss直聘采集失败: {e}")

    if args.platform in ("both", "liepin"):
        try:
            print("[jobs] 正在从 猎聘 (CDP) 采集...")
            liepin_jobs = search_liepin_jobs(args.keyword, top_k=args.top_k, cdp_url=cdp_url, city=args.city)
            jobs.extend(liepin_jobs)
            print(f"[jobs] 猎聘采集到 {len(liepin_jobs)} 条")
        except Exception as e:
            print(f"[jobs] 猎聘采集失败: {e}")

    if not jobs:
        print("[jobs] 采集结果为空")
        return 1

    n = store.upsert(jobs, args.keyword)
    print(f"[jobs] 入库 {n} 条（指纹去重）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
