"""search_jobs mock 工具（E2）：职位 JD 搜索（MVP 用 mock 数据，N 阶段接真实 MCP）。"""
from __future__ import annotations

import json

from langchain_core.tools import tool

# mock JD 库：大模型应用 / Agent / RAG / Java 方向
_MOCK_JOBS = [
    {"company": "字节跳动", "title": "大模型应用工程师", "city": "北京", "salary": "30-50K",
     "skills": ["Python", "LangChain", "LangGraph", "RAG", "Agent", "向量数据库"],
     "jd": "负责大模型 Agent 应用开发：RAG 系统、Function Calling、多智能体编排。要求 Python/LangChain/LangGraph，熟悉向量检索。"},
    {"company": "阿里", "title": "算法工程师-大模型", "city": "杭州", "salary": "35-60K",
     "skills": ["Python", "PyTorch", "微调", "RAG", "多模态"],
     "jd": "大模型微调与 RAG 系统开发，多模态理解。要求 Python/PyTorch，有 LLM 训练或应用经验。"},
    {"company": "美团", "title": "后端开发工程师-Java+大模型", "city": "北京", "salary": "30-45K",
     "skills": ["Java", "Spring", "LLM", "Agent", "微服务"],
     "jd": "Java 后端 + 大模型应用集成：LLM 接口封装、Agent 编排、Spring Boot 微服务。"},
    {"company": "腾讯", "title": "大模型应用开发", "city": "深圳", "salary": "30-50K",
     "skills": ["Python", "RAG", "Agent", "Prompt Engineering"],
     "jd": "LLM 应用开发：Prompt 工程、RAG、Function Calling、多智能体协同。"},
    {"company": "百度", "title": "资深大模型应用工程师", "city": "北京", "salary": "40-60K",
     "skills": ["Python", "LangGraph", "Agent", "RAG", "MCP"],
     "jd": "多智能体系统架构，Agentic RAG，MCP 工具生态。要求熟悉 LangGraph/Agent 编排。"},
    {"company": "蚂蚁集团", "title": "AI 应用开发工程师", "city": "杭州", "salary": "30-45K",
     "skills": ["Java", "Python", "LLM", "RAG", "Spring AI"],
     "jd": "Java/Spring AI 接入大模型，AI 应用落地，RAG 检索系统。"},
    {"company": "小红书", "title": "大模型算法工程师", "city": "上海", "salary": "35-55K",
     "skills": ["Python", "PyTorch", "SFT", "RLHF", "RAG"],
     "jd": "LLM 对齐与 RAG，内容理解。要求熟悉 SFT/RLHF，有 LLM 经验。"},
    {"company": "理想汽车", "title": "AI 平台后端工程师", "city": "北京", "salary": "30-45K",
     "skills": ["Java", "Go", "LLM", "推理服务", "vLLM"],
     "jd": "大模型推理服务与 AI 平台后端，vLLM/推理优化，Java/Go。"},
]


@tool
def search_jobs(direction: str, top_k: int = 5) -> str:
    """按求职方向搜索职位 JD（MVP 用 mock 数据，N 阶段接真实 MCP）。

    Args:
        direction: 求职方向（如"大模型应用"、"Java 后端"、"算法"）。
        top_k: 返回条数。
    """
    kw = direction.lower()
    matches = [
        j for j in _MOCK_JOBS
        if kw in (j["jd"] + " " + j["title"] + " " + " ".join(j["skills"])).lower()
    ]
    if not matches:
        matches = _MOCK_JOBS  # 方向无精确匹配则全量返回，由 agent 自己评估
    return json.dumps(matches[:top_k], ensure_ascii=False)
