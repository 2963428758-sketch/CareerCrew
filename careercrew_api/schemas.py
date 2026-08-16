"""pydantic 请求/响应模型（§4 API 端点）。"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# ── 通用 ──


class HealthResponse(BaseModel):
    status: str = "ok"
    model: str = ""
    embedding: str = ""
    vector_store: str = ""
    ready: bool = False
    error: str | None = None


# ── Auth ──


class CredentialsRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    # 登录要能接受临时默认密码（如 123456），只做长度上限约束
    password: str = Field(min_length=1, max_length=256)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str | None = Field(default=None, max_length=64)  # 留空=默认 123456，首次登录强制改密
    role: Literal["user", "admin", "quality_reviewer"] = "user"


class PublicUser(BaseModel):
    id: str
    username: str
    role: Literal["user", "admin", "quality_reviewer"]
    must_change_password: bool = False


class AccountListItem(BaseModel):
    id: str
    username: str
    role: Literal["user", "admin", "quality_reviewer"]
    status: Literal["active", "disabled"]
    token_version: int
    must_change_password: bool = False
    created_at: str
    updated_at: str


class UserListResponse(BaseModel):
    items: list[AccountListItem]
    total: int
    page: int
    page_size: int


class UserPatchRequest(BaseModel):
    role: Literal["user", "admin", "quality_reviewer"] | None = None
    status: Literal["active", "disabled"] | None = None

    @model_validator(mode="after")
    def _at_least_one(self):
        if self.role is None and self.status is None:
            raise ValueError("至少提供 role 或 status 之一")
        return self


class PasswordResetRequest(BaseModel):
    password: str | None = Field(default=None, max_length=64)  # 留空=默认 123456，下次登录强制改密


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(default="", max_length=256)  # 强制改密流程可留空
    new_password: str = Field(min_length=8, max_length=64)

    @field_validator("new_password")
    @classmethod
    def _policy(cls, value: str) -> str:
        if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
            raise ValueError("密码需为 8-64 位，且同时包含字母和数字")
        return value


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
    expires_in: int
    user: PublicUser


# ── Chat（M1 对话闭环）──


class Mention(BaseModel):
    """@ 引用资源。type ∈ {knowledge_document, resume}；不支持 @Agent。

    id 不可信：服务端必须再次校验 ownership / visibility，逐条 resolve。
    """

    type: Literal["knowledge_document", "resume"]
    id: str = Field(min_length=1, max_length=255)


class MatchRequest(BaseModel):
    intent: str
    thread_id: str = "m1"
    mentions: list[Mention] = Field(default_factory=list)
    # T3.5：本轮允许 Agent 使用的工具 id 列表（None/空=默认全部 server allowlist）
    tools: list[str] | None = None


class ResumeRequest(BaseModel):
    jd_text: str
    thread_id: str = "m1"
    mentions: list[Mention] = Field(default_factory=list)
    # T3.5：本轮允许 Agent 使用的工具 id 列表（None/空=默认全部 server allowlist）
    tools: list[str] | None = None


# ── Interview ──


class QuestionRequest(BaseModel):
    topic: str = ""
    thread_id: str = "interview"
    mentions: list[Mention] = Field(default_factory=list)


class InterviewChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = ""


class InterviewChatRequest(BaseModel):
    topic: str = ""
    messages: list[InterviewChatMessage] = []
    thread_id: str = "interview"
    mentions: list[Mention] = Field(default_factory=list)


class ScoreRequest(BaseModel):
    question: str
    answer: str
    max_score: int = 10


class ScoreResponse(BaseModel):
    score: float
    feedback: str


class RecordRequest(BaseModel):
    entries: list[dict]
    thread_id: str = "interview"


class RecordResponse(BaseModel):
    saved: int


# ── Resume ──


class GenerateRequest(BaseModel):
    user_resume: str
    jd: str = ""
    thread_id: str = "m1"


class ResumeChatRequest(BaseModel):
    """对话式简历优化：question 为当前轮输入；resume_text 仅在新上传时携带，
    后端按 thread_id 存储简历，后续轮次自动复用。"""

    question: str
    resume_text: str = ""
    jd: str = ""
    thread_id: str = "m1"


# ── Consult（会诊）──


class ConsultRequest(BaseModel):
    question: str
    # 会诊已改为总调度官自动编排；该字段仅为向后兼容保留，后端会忽略它。
    agents: list[str] = Field(default_factory=list)
    thread_id: str = "consult"
    # 前端"资料填写框"提交的结构化用户画像（current_position / experience_years /
    # skills / target_direction / city / salary / target_companies），后端并入会诊上下文。
    profile: dict[str, str] = Field(default_factory=dict)
    mentions: list[Mention] = Field(default_factory=list)


# ── Knowledge（知识库问答）──


class KnowledgeAskRequest(BaseModel):
    question: str = Field(min_length=1)
    thread_id: str = "knowledge"
    category: str = ""  # resume / knowledge / interview，空串=全部
    scope: str = "all"  # all（公共+本人私有）| public | private
    mentions: list[Mention] = Field(default_factory=list)  # 强制上下文（§15）
    # T3.5：本轮允许 Agent 使用的工具 id 列表（None/空=默认全部 server allowlist）
    tools: list[str] | None = None
