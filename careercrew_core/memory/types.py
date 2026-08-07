"""记忆核心数据类型（C1）。

MemoryEntry：情景记忆条目（append-only JSONL 一行），id + parentId 构成树。
UserModel：长期用户画像（结构化，跨会话）。
TreeNode：树节点（entry + children），供树遍历。

append-only 树的红利：会话只增不改，任何历史轨迹可完整回放 -- 轨迹级评估（黄金轨迹
回放）的基础（DEV_SPEC 3.3.2）。
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
