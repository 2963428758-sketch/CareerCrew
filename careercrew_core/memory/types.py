"""记忆核心数据类型。

MemoryEntry：情景记忆条目（append-only），id + parentId 构成树。
SemanticFact：语义记忆事实（带来源/置信度/版本，跨会话）。
MemoryPolicy：Codex 式治理开关（生成/使用分离）。
UserModel：长期用户画像投影（由语义事实聚合，兼容旧前端契约）。
TreeNode：树节点（entry + children），供树遍历。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

# 情景记忆事件类型
MEMORY_TYPES = {
    "session_start",   # 会话开始
    "interview_qa",    # 面试问答
    "job_match",       # 职位匹配命中
    "application",     # 投递
    "offer",           # offer
    "salary_talk",     # 谈薪
    "review",          # 复盘
    "compaction",      # 压缩条目（I 阶段）
    "note",            # 其他备注
}


class MemoryEntry(BaseModel):
    """情景记忆条目（append-only JSONL 一行）。id/ts 在 EpisodicMemory.write 时自动填。"""

    id: str = ""
    parentId: str | None = None
    type: str  # MEMORY_TYPES 之一
    ts: str = ""  # ISO 8601
    content: dict | str  # 类型相关内容


class TreeNode(BaseModel):
    """树节点（entry + children），供树遍历。"""

    entry: MemoryEntry
    children: list["TreeNode"] = Field(default_factory=list)


class SemanticFact(BaseModel):
    """语义记忆事实：关于用户的稳定信息，带来源/置信度/版本。"""

    user_id: str
    name: str  # 唯一键（如 profile.skills / preference.salary_min）
    type: str  # profile | preference | target_company | mastery | note
    description: str = ""  # 一行摘要，供 LLM 路由选择
    content: dict = Field(default_factory=dict)
    source: str = ""  # 来源（agent / 会话 / consolidation）
    confidence: float = 1.0
    version: int = 1
    created_at: str = ""
    modified_at: str = ""


class MemoryPolicy(BaseModel):
    """Codex 式记忆治理：全局 + 用户级生成/使用分离开关。"""

    user_id: str = ""
    enabled: bool = False
    generate: bool = True
    use: bool = True
    updated_at: str = ""


class UserProfile(BaseModel):
    """用户能力画像。"""

    skills: list[str] = Field(default_factory=list)
    level: str = ""  # 初级 | 中级 | 高级
    direction: str = ""  # 大模型应用 / Agent / Java 后端 等
    experience_years: int | None = None


class UserPreferences(BaseModel):
    """求职偏好。"""

    salary_min: float | None = None  # K/月
    salary_max: float | None = None
    city: list[str] = Field(default_factory=list)
    work_mode: str = ""  # 现场 | 远程 | 混合


class UserModel(BaseModel):
    """长期 User Model（跨会话用户画像，结构化）。"""

    user_id: str
    profile: UserProfile = Field(default_factory=UserProfile)
    target_companies: list[str] = Field(default_factory=list)
    preferences: UserPreferences = Field(default_factory=UserPreferences)
    interview_mastery: dict[str, float] = Field(default_factory=dict)  # {topic: 0-1}
