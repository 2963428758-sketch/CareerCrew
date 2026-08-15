"""从 Exa 语义搜索抓取大模型/Agent/RAG 语料，经标准知识库管线入库。

输出：data/uploads/knowledge_raw/{user_id}/{uuid}.md（不再写 data/knowledge）。
入库 metadata：owner_user_id + visibility（private 仅本人可见；public 面向全部用户）。

Exa key 从 ~/.mcporter/mcporter.json 读（不硬编码）。
跑法：$env:PYTHONPATH=(Get-Location).Path; python scripts/fetch_kb.py [--visibility public] [--no-ingest]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse as up
from pathlib import Path
from uuid import uuid4

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def get_exa_key() -> str:
    p = os.path.expanduser("~/.mcporter/mcporter.json")
    data = json.load(open(p, encoding="utf-8"))
    url = data["mcpServers"]["exa"]["baseUrl"]  # https://mcp.exa.ai/mcp?exaApiKey=KEY
    return up.parse_qs(up.urlparse(url).query)["exaApiKey"][0]


def exa_search(key: str, query: str, num: int = 4, max_chars: int = 4000) -> list[dict]:
    resp = requests.post(
        "https://api.exa.ai/search",
        headers={"x-api-key": key, "Content-Type": "application/json"},
        json={"query": query, "numResults": num, "contents": {"text": {"maxCharacters": max_chars}}},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def save_topic(target: Path, filename: str, query: str, key: str,
               num: int = 4) -> tuple[int, int]:
    results = exa_search(key, query, num=num)
    lines = [f"# {filename.replace('.md', '')} 知识库（Exa 搜索聚合）\n"]
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "").strip()
        url = r.get("url") or ""
        text = (r.get("text") or "").strip()
        lines.append(f"\n## [{i}] {title}\n")
        lines.append(f"来源: {url}\n")
        lines.append(f"\n{text}\n")
    target.write_text("\n".join(lines), encoding="utf-8")
    return len(results), sum(len(r.get("text") or "") for r in results)


def ingest_markdown(path: Path, user_id: str, visibility: str) -> int:
    from careercrew_ai.embedding import create_embedding
    from careercrew_ai.vector_store import create_vector_store
    from careercrew_core.rag.categories import category_for_doc
    from careercrew_core.rag.pipeline_multimodal import MultimodalIngestionPipeline
    from careercrew_core.state.settings import load_settings

    settings = load_settings()
    pipeline = MultimodalIngestionPipeline(
        create_embedding(settings), create_vector_store(settings),
        contextual=False, output_dir=settings.rag.loaders.output_dir,
        loader_provider=settings.rag.loaders.provider,
        loader_api_key=settings.rag.loaders.api_key,
        loader_device=settings.rag.loaders.device,
        loader_method=settings.rag.loaders.method,
        loader_formula=settings.rag.loaders.formula,
        loader_table=settings.rag.loaders.table,
        loader_language=settings.rag.loaders.language,
        loader_model_version=settings.rag.loaders.model_version,
        loader_poll_interval=settings.rag.loaders.poll_interval,
        loader_timeout=settings.rag.loaders.timeout,
        chunk_size=settings.rag.chunking.chunk_size,
        chunk_overlap=settings.rag.chunking.chunk_overlap,
    )
    return pipeline.ingest_file(
        path,
        metadata={"owner_user_id": user_id, "visibility": visibility},
        category=category_for_doc(path.name),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", default="u_001")
    parser.add_argument("--visibility", default="private", choices=["private", "public"])
    parser.add_argument("--no-ingest", action="store_true", help="只抓取落盘，不入库")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(PROJECT_ROOT))
    from careercrew_api import storage

    key = get_exa_key()
    topics = [
        ("exa_rag_interview.md", "大模型 RAG 检索增强生成 面试题 八股 向量检索 rerank 混合检索"),
        ("exa_interview_experience.md", "大模型算法岗 面经 字节 阿里 美团 面试经历 大厂"),
        ("exa_career_planning.md", "大模型应用 求职职业规划 方向选择 学习路线 Agent 工程师 成长路径"),
    ]
    total_results = 0
    total_chars = 0
    for fname, q in topics:
        target = storage.resolve_under(
            storage.L.knowledge_raw, args.user_id, f"{uuid4().hex[:12]}.md"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        n, chars = save_topic(target, fname, q, key, num=4)
        print(f"  {fname}: {n} 条结果, {chars} 字符 -> {target}")
        total_results += n
        total_chars += chars
        if not args.no_ingest:
            points = ingest_markdown(target, args.user_id, args.visibility)
            print(f"    入库 {points} 点（visibility={args.visibility}）")
    print(f"\n总计: {total_results} 条结果, {total_chars} 字符"
          f"（user={args.user_id}, visibility={args.visibility}）")


if __name__ == "__main__":
    main()
