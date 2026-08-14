"""pydantic 请求/响应模型（§4 API 端点）。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
    password: str = Field(min_length=12, max_length=256)


class CreateUserRequest(CredentialsRequest):
    role: Literal["user", "admin"] = "user"


class PublicUser(BaseModel):
    id: str
    username: str
    role: Literal["user", "admin"]


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
    expires_in: int
    user: PublicUser


# ── Chat（M1 对话闭环）──


class MatchRequest(BaseModel):
    intent: str
    thread_id: str = "m1"
    user_id: str = "u_001"


class ResumeRequest(BaseModel):
    jd_text: str
    thread_id: str = "m1"
    user_id: str = "u_001"


# ── Interview ──


class QuestionRequest(BaseModel):
    topic: str = ""
    thread_id: str = "interview"
    user_id: str = "u_001"


class InterviewChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = ""


class InterviewChatRequest(BaseModel):
    topic: str = ""
    messages: list[InterviewChatMessage] = []
    thread_id: str = "interview"
    user_id: str = "u_001"


class ScoreRequest(BaseModel):
    question: str
    answer: str
    max_score: int = 10


class ScoreResponse(BaseModel):
    score: float
    feedback: str


class RecordRequest(BaseModel):
    entries: list[dict]


class RecordResponse(BaseModel):
    saved: int


# ── Resume ──


class GenerateRequest(BaseModel):
    user_resume: str
    jd: str = ""
    thread_id: str = "m1"
    user_id: str = "u_001"


class ResumeChatRequest(BaseModel):
    """对话式简历优化：question 为当前轮输入；resume_text 仅在新上传时携带，
    后端按 thread_id 存储简历，后续轮次自动复用。"""

    question: str
    resume_text: str = ""
    jd: str = ""
    thread_id: str = "m1"
    user_id: str = "u_001"


# ── Consult（会诊）──


class ConsultRequest(BaseModel):
    question: str
    # 会诊已改为总调度官自动编排；该字段仅为向后兼容保留，后端会忽略它。
    agents: list[str] = Field(default_factory=list)
    thread_id: str = "consult"
    user_id: str = "u_001"
    # 前端"资料填写框"提交的结构化用户画像（current_position / experience_years /
    # skills / target_direction / city / salary / target_companies），后端并入会诊上下文。
    profile: dict[str, str] = Field(default_factory=dict)


# ── Knowledge（知识库问答）──


class KnowledgeAskRequest(BaseModel):
    question: str = Field(min_length=1)
    thread_id: str = "knowledge"
    user_id: str = "u_001"
    category: str = ""  # resume / knowledge / interview，空串=全部
