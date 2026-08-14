"""知识库内容分类：简历 / 学习资料 / 面试题 / 岗位 JD。

每个向量点打 `category` metadata，检索时可按分类过滤。
"""
from __future__ import annotations

CATEGORY_RESUME = "resume"        # 简历
CATEGORY_KNOWLEDGE = "knowledge"  # 学习资料（课程 / 文档；展示名"学习资料"）
CATEGORY_INTERVIEW = "interview"  # 面试题 / 面经
CATEGORY_JOB = "job"              # 岗位 JD / 招聘信息

CATEGORY_LABELS: dict[str, str] = {
    CATEGORY_RESUME: "简历",
    CATEGORY_KNOWLEDGE: "学习资料",
    CATEGORY_INTERVIEW: "面试题",
    CATEGORY_JOB: "岗位/JD",
}

ALL_CATEGORIES = (CATEGORY_RESUME, CATEGORY_KNOWLEDGE, CATEGORY_INTERVIEW, CATEGORY_JOB)


def category_for_doc(doc_id: str) -> str:
    """按文档名启发式判断分类（上传未显式指定时用）。"""
    d = (doc_id or "").lower()
    if any(k in d for k in ("简历", "resume", "求职")):
        return CATEGORY_RESUME
    if any(k in d for k in ("面试", "面经", "八股", "interview", "question")):
        return CATEGORY_INTERVIEW
    if any(k in d for k in ("岗位", "jd", "job", "招聘", "offer")):
        return CATEGORY_JOB
    return CATEGORY_KNOWLEDGE


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category or "全部")


# agent kind -> rag_query 检索分类（str 单分类 / list 多分类；不含=不过滤）。
# 面试官同时检索面经/八股 + 简历范本，可搭配用户简历出题。
AGENT_RAG_CATEGORIES: dict[str, str | list[str]] = {
    "matcher": CATEGORY_JOB,                       # 职位匹配：真实 JD
    "resume": CATEGORY_RESUME,                     # 简历顾问：简历范本/写作要点
    "interviewer": [CATEGORY_INTERVIEW, CATEGORY_RESUME],  # 面试官：面经/八股 + 简历
    "salary": CATEGORY_JOB,                        # 薪资谈判：岗位/JD/公司信息
    "planner": CATEGORY_KNOWLEDGE,                 # 职业规划：学习资料/职业规划
}


def categories_for_agent(kind: str) -> str | list[str] | None:
    """agent kind -> rag_query 分类；未知 kind 返回 None（= 不过滤，检索全部）。"""
    return AGENT_RAG_CATEGORIES.get(kind)
