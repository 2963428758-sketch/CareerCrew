"""从 Exa 语义搜索抓取大模型/Agent/RAG 知识库内容到 data/knowledge/。

Exa key 从 ~/.mcporter/mcporter.json 读（不硬编码）。
跑法：conda run -n careercrew python scripts/fetch_kb.py
"""
from __future__ import annotations

import json
import os
import urllib.parse as up
from pathlib import Path

import requests


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


def save_topic(key: str, filename: str, query: str, num: int = 4) -> tuple[int, int]:
    results = exa_search(key, query, num=num)
    out = Path("data/knowledge") / filename
    lines = [f"# {filename.replace('.md', '')} 知识库（Exa 搜索聚合）\n"]
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "").strip()
        url = r.get("url") or ""
        text = (r.get("text") or "").strip()
        lines.append(f"\n## [{i}] {title}\n")
        lines.append(f"来源: {url}\n")
        lines.append(f"\n{text}\n")
    out.write_text("\n".join(lines), encoding="utf-8")
    return len(results), sum(len(r.get("text") or "") for r in results)


def main() -> None:
    key = get_exa_key()
    topics = [
        ("exa_rag_interview.md", "大模型 RAG 检索增强生成 面试题 八股 向量检索 rerank 混合检索"),
        ("exa_agent_interview.md", "LangChain LangGraph Agent ReAct 多智能体 面试题 function calling 工具调用"),
        ("exa_llm_fundamentals.md", "大模型 Transformer Attention 训练 SFT RLHF 推理优化 KV cache 量化 八股"),
        ("exa_interview_experience.md", "大模型算法岗 面经 字节 阿里 美团 面试经历 大厂"),
        ("exa_jd.md", "大模型应用工程师 招聘 JD 岗位职责 任职要求 LLM Agent RAG"),
        ("exa_resume.md", "大模型应用工程师 简历范本 项目经验 RAG Agent 简历模板 求职"),
        # 第二批：补薄弱主题（checkpointer/谈薪/职业规划/Java+大模型/chunking）
        ("exa_langgraph.md", "LangGraph checkpointer 状态持久化 SQLite interrupt HITL 人工干预 状态机 编排"),
        ("exa_negotiation.md", "薪资谈判 谈薪策略 offer 薪资期望 HR 求职 报价 技巧"),
        ("exa_career_planning.md", "大模型应用 求职职业规划 方向选择 学习路线 Agent 工程师 成长路径"),
        ("exa_java_llm.md", "Java 大模型 Spring AI LangChain4j 后端接入 LLM 应用集成 智能体"),
        ("exa_chunking.md", "RAG chunking 分块策略 Contextual Chunking 递归切分 文档切分 策略 选型"),
    ]
    total_results = 0
    total_chars = 0
    for fname, q in topics:
        n, chars = save_topic(key, fname, q)
        print(f"  {fname}: {n} 条结果, {chars} 字符")
        total_results += n
        total_chars += chars
    print(f"\n总计: {total_results} 条结果, {total_chars} 字符 -> data/knowledge/")


if __name__ == "__main__":
    main()
